"""Tour lifecycle, ported from the bot's conversation flow.

draft (preview: addresses selected, nothing reserved)
  -> active (addresses marked PLANNED: hidden from other militants)
  -> completed (unvisited addresses released back to TO_VISIT)
"""
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.contrib.gis.geos import LineString, Point, Polygon
from django.db import transaction
from django.db.models import BooleanField, FloatField
from django.db.models.expressions import RawSQL
from django.utils import timezone

from canvassing.models import (
    RESULT_TO_STATUS,
    SUCCESS_RESULTS,
    Address,
    Area,
    Status,
    Tour,
    TourStop,
    Visit,
    VisitResult,
)

from . import routing
from .geo import LatLon, bbox_around, haversine_matrix
from .tsp import solve_open_path


class TourError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _point(p: LatLon) -> Point:
    return Point(p[1], p[0], srid=4326)


def _linestring(points: list[LatLon]) -> LineString:
    return LineString([(lon, lat) for lat, lon in points], srid=4326)


def _to_visit(user):
    return Address.objects.filter(scope_id=user.scope_id, status=Status.TO_VISIT)


# --------------------------------------------------------------------------- housekeeping


def expire_stale_tours() -> None:
    """Drop abandoned previews and close tours left open (the bot's 24h conversation timeout)."""
    now = timezone.now()
    Tour.objects.filter(
        status=Tour.TourStatus.DRAFT,
        created_at__lt=now - timedelta(hours=settings.CANVASSING_DRAFT_TIMEOUT_HOURS),
    ).delete()
    stale = Tour.objects.filter(
        status=Tour.TourStatus.ACTIVE,
        started_at__lt=now - timedelta(hours=settings.CANVASSING_TOUR_TIMEOUT_HOURS),
    )
    for tour in stale:
        finish_tour(tour)


def current_tour(user) -> Tour | None:
    return (
        Tour.objects.filter(user=user, status__in=[Tour.TourStatus.ACTIVE, Tour.TourStatus.DRAFT])
        .order_by("-created_at")
        .first()
    )


def _prepare_slot(user) -> None:
    if Tour.objects.filter(user=user, status=Tour.TourStatus.ACTIVE).exists():
        raise TourError("Tu as déjà une tournée en cours. Termine-la avant d'en préparer une nouvelle.", 409)
    Tour.objects.filter(user=user, status=Tour.TourStatus.DRAFT).delete()


def _create_draft(user, addresses: list[Address], order: list[int], **fields) -> Tour:
    """`order` indexes into [start] + addresses (+ [end]); index 0 = start point."""
    max_stops = settings.CANVASSING_MAX_STOPS
    tour = Tour.objects.create(user=user, scope_id=user.scope_id, **fields)
    stops = []
    for idx in order:
        if 1 <= idx <= len(addresses):
            stops.append(TourStop(tour=tour, address=addresses[idx - 1], position=len(stops)))
    TourStop.objects.bulk_create(stops[:max_stops])
    return tour


# --------------------------------------------------------------------------- tour creation


def prepare_free_tour(user, start: LatLon, end: LatLon, radius_km: float) -> Tour:
    """Free tour: addresses within `radius_km` of the walking route between start and end."""
    _prepare_slot(user)
    max_stops = settings.CANVASSING_MAX_STOPS

    ideal_route = routing.route_through([start, end])
    route_wkt = _linestring(ideal_route.geometry).wkt
    min_lon, min_lat, max_lon, max_lat = bbox_around(ideal_route.geometry, radius_km)
    radius_m = radius_km * 1000

    candidates = list(
        _to_visit(user)
        .filter(location__within=Polygon.from_bbox((min_lon, min_lat, max_lon, max_lat)))
        .alias(
            near_route=RawSQL(
                "ST_DWithin(location::geography, ST_GeomFromText(%s, 4326)::geography, %s)",
                (route_wkt, radius_m),
                output_field=BooleanField(),
            )
        )
        .filter(near_route=True)
        .annotate(
            route_distance=RawSQL(
                "ST_Distance(location::geography, ST_GeomFromText(%s, 4326)::geography)",
                (route_wkt,),
                output_field=FloatField(),
            )
        )
        .order_by("route_distance")[: max_stops + 1]
    )
    if not candidates:
        raise TourError("Aucune adresse à visiter trouvée dans ce rayon. Essaie un rayon plus grand.", 404)

    too_many = len(candidates) > max_stops
    candidates = candidates[:max_stops]
    points = [start] + [(a.lat, a.lon) for a in candidates] + [end]
    order = solve_open_path(haversine_matrix(points), fixed_end=True)

    return _create_draft(
        user,
        candidates,
        order,
        kind=Tour.Kind.FREE,
        start_point=_point(start),
        end_point=_point(end),
        radius_km=radius_km,
        route=_linestring(ideal_route.geometry),
        route_distance_m=ideal_route.distance_m,
        route_duration_s=ideal_route.duration_s,
        route_approximate=ideal_route.approximate,
        too_many_addresses=too_many,
    )


def prepare_predefined_tour(user, area: Area, start: LatLon) -> Tour:
    """Predefined tour: every address to visit inside a coordinator-defined area, optimally ordered."""
    _prepare_slot(user)
    max_stops = settings.CANVASSING_MAX_STOPS

    addresses = list(_to_visit(user).filter(location__within=area.geometry).order_by("id")[: max_stops + 1])
    if not addresses:
        raise TourError(f"Aucune adresse à visiter trouvée dans la zone « {area.name} ».", 404)
    too_many = len(addresses) > max_stops
    addresses = addresses[:max_stops]

    points = [start] + [(a.lat, a.lon) for a in addresses]
    order = solve_open_path(routing.distance_matrix(points))
    route = routing.route_through([points[i] for i in order])

    return _create_draft(
        user,
        addresses,
        order,
        kind=Tour.Kind.PREDEFINED,
        area=area,
        start_point=_point(start),
        route=_linestring(route.geometry),
        route_distance_m=route.distance_m,
        route_duration_s=route.duration_s,
        route_approximate=route.approximate,
        too_many_addresses=too_many,
    )


# --------------------------------------------------------------------------- tour progress


@transaction.atomic
def start_tour(tour: Tour) -> Tour:
    """Reserve the addresses (PLANNED). Addresses taken by someone else in the meantime are dropped."""
    if tour.status != Tour.TourStatus.DRAFT:
        raise TourError("Cette tournée a déjà démarré.", 409)

    stops = list(tour.stops.select_related("address"))
    available = set(
        Address.objects.select_for_update()
        .filter(id__in=[s.address_id for s in stops], status=Status.TO_VISIT)
        .values_list("id", flat=True)
    )
    kept = [s for s in stops if s.address_id in available]
    if not kept:
        tour.delete()
        raise TourError("Ces adresses viennent d'être prises par d'autres militant·es. Prépare une nouvelle tournée.", 409)

    TourStop.objects.filter(tour=tour).exclude(id__in=[s.id for s in kept]).delete()
    for position, stop in enumerate(kept):
        stop.position = position
    TourStop.objects.bulk_update(kept, ["position"])

    now = timezone.now()
    Address.objects.filter(id__in=available).update(
        status=Status.PLANNED, visit_planned_by=tour.user, visit_planned_at=now
    )
    tour.status = Tour.TourStatus.ACTIVE
    tour.started_at = now
    tour.save(update_fields=["status", "started_at"])
    return tour


def apply_result(user, addresses: list[Address], result: str, tour: Tour | None = None, stop: TourStop | None = None):
    now = timezone.now()
    Address.objects.filter(id__in=[a.id for a in addresses]).update(
        status=RESULT_TO_STATUS[VisitResult(result)], visit_planned_by=user, visit_planned_at=now
    )
    if stop is not None:
        Visit.objects.update_or_create(
            stop=stop, defaults={"address": stop.address, "user": user, "tour": tour, "result": result}
        )
    else:
        Visit.objects.bulk_create([Visit(address=a, user=user, result=result) for a in addresses])


@transaction.atomic
def record_stop_result(tour: Tour, stop: TourStop, result: str) -> TourStop:
    if tour.status != Tour.TourStatus.ACTIVE:
        raise TourError("Cette tournée n'est pas en cours.", 409)
    stop.result = result
    stop.visited_at = timezone.now()
    stop.save(update_fields=["result", "visited_at"])
    apply_result(tour.user, [stop.address], result, tour=tour, stop=stop)
    return stop


@transaction.atomic
def finish_tour(tour: Tour) -> Tour:
    if tour.status == Tour.TourStatus.COMPLETED:
        return tour
    unvisited_ids = tour.stops.filter(result="").values_list("address_id", flat=True)
    Address.objects.filter(id__in=unvisited_ids, status=Status.PLANNED, visit_planned_by=tour.user).update(
        status=Status.TO_VISIT
    )
    tour.status = Tour.TourStatus.COMPLETED
    tour.ended_at = timezone.now()
    tour.save(update_fields=["status", "ended_at"])
    return tour


def tour_summary(tour: Tour) -> dict:
    counts = Counter(tour.stops.exclude(result="").values_list("result", flat=True))
    summary = {r.value: counts.get(r.value, 0) for r in VisitResult}
    summary["total_success"] = sum(counts.get(r.value, 0) for r in SUCCESS_RESULTS)
    summary["not_visited"] = tour.stops.filter(result="").count()
    return summary
