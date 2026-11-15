import json

from rest_framework import serializers

from .models import AbsentDetail, Address, District, Tour, TourStop, VisitResult


class PointSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        return (value["lat"], value["lon"])


def point_to_dict(point) -> dict | None:
    return None if point is None else {"lat": point.y, "lon": point.x}


def address_to_dict(address: Address, with_names: bool = True) -> dict:
    data = {
        "id": address.id,
        "address": address.address,
        "zip_code": address.zip_code,
        "city": address.city,
        "label": address.full_address,
        "lat": address.lat,
        "lon": address.lon,
    }
    if with_names:
        # Full name: the militant needs it to find the right doorbell.
        data["name"] = address.name
        data["first_name"] = address.first_name
        data["first_names"] = address.first_names
        data["birth_year"] = address.birth_year
    return data


def geojson(geometry) -> dict | None:
    return None if geometry is None else json.loads(geometry.geojson)


def with_outline(queryset):
    """Districts with their simplified outline as GeoJSON text, coordinates rounded to ~1 m (lighter map)."""
    from django.contrib.gis.db.models.functions import AsGeoJSON

    return queryset.defer("geometry", "geometry_simple").annotate(outline=AsGeoJSON("geometry_simple", precision=5))


def district_to_dict(district: District, n_to_visit: int | None = None, done_pct: float | None = None) -> dict:
    """Compact form (map, lists): the simplified outline only."""
    data = {
        "id": district.id,
        "code": district.code,
        "name": district.name,
        "score": district.score,
        # `outline`: GeoJSON text annotated by the query (rounded coordinates, see `with_outline`).
        "geometry": json.loads(o) if (o := getattr(district, "outline", None)) else geojson(district.geometry_simple or district.geometry),
        "label": point_to_dict(district.label_point),
    }
    if n_to_visit is not None:
        data["n_to_visit"] = n_to_visit
    if done_pct is not None:
        data["done_pct"] = done_pct
    return data


def short_name(user) -> str:
    """"Camille M." — enough to recognise each other, without exposing full names across organizations."""
    first = user.first_name.strip() or "Militant·e"
    return f"{first} {user.last_name.strip()[0]}." if user.last_name.strip() else first


def stop_to_dict(stop: TourStop, last_visit: dict | None = None) -> dict:
    return {
        "id": stop.id,
        "position": stop.position,
        "result": stop.result or None,
        "absent_detail": stop.absent_detail or None,
        "visited_at": stop.visited_at,
        # Last time someone knocked at this door (in another tour, possibly for a past election), if ever.
        "last_visit": last_visit,
        "address": address_to_dict(stop.address),
    }


def last_visit_by_address(tour: Tour, address_ids) -> dict:
    from .models import Visit
    from .services.elections import phrase

    visits = (
        Visit.objects.filter(address_id__in=address_ids)
        .exclude(tour=tour)
        .select_related("user", "election")
        .order_by("address_id", "-created_at")
        .distinct("address_id")
    )
    return {
        v.address_id: {
            "at": v.created_at,
            "by": short_name(v.user) if v.user else None,
            "result": v.result,
            "detail": v.absent_detail or None,
            "election": phrase(v.election) or None,  # "pour l'élection consulaire 2026"
            "current_election": bool(v.election and v.election.is_current),
        }
        for v in visits
    }


def tour_to_dict(tour: Tour) -> dict:
    from .services.tours import tour_summary

    stops = list(tour.stops.select_related("address"))
    last_visit = last_visit_by_address(tour, [s.address_id for s in stops])
    return {
        "id": tour.id,
        "kind": tour.kind,
        "status": tour.status,
        "area": {"id": tour.area_id, "name": tour.area.name} if tour.area_id else None,
        "start": point_to_dict(tour.start_point),
        "end": point_to_dict(tour.end_point),
        "radius_km": tour.radius_km,
        "route": [[lat, lon] for lon, lat in tour.route.coords] if tour.route else None,
        "route_distance_m": tour.route_distance_m,
        "route_duration_s": tour.route_duration_s,
        "route_approximate": tour.route_approximate,
        "too_many_addresses": tour.too_many_addresses,
        "created_at": tour.created_at,
        "started_at": tour.started_at,
        "ended_at": tour.ended_at,
        "stops": [stop_to_dict(s, last_visit.get(s.address_id)) for s in stops],
        "summary": tour_summary(tour),
    }


class CreateTourSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=Tour.Kind.choices)
    start = PointSerializer()
    end = PointSerializer(required=False)
    radius_km = serializers.FloatField(required=False, min_value=0.05, max_value=10)
    area_id = serializers.IntegerField(required=False)

    def validate(self, attrs):
        if attrs["kind"] == Tour.Kind.FREE:
            missing = [f for f in ("end", "radius_km") if f not in attrs]
        else:
            missing = [f for f in ("area_id",) if f not in attrs]
        if missing:
            raise serializers.ValidationError({f: "Ce champ est obligatoire." for f in missing})
        return attrs


class FreeTourPreviewSerializer(serializers.Serializer):
    start = PointSerializer()
    end = PointSerializer()
    radius_km = serializers.FloatField(min_value=0.05, max_value=10)


class ResultSerializer(serializers.Serializer):
    result = serializers.ChoiceField(choices=VisitResult.choices)
    # Only for "absent": leaflet left in the mailbox, or mailbox out of reach.
    absent_detail = serializers.ChoiceField(choices=AbsentDetail.choices, required=False, allow_blank=True, default="")


class StopsResultSerializer(ResultSerializer):
    stop_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1, max_length=50)


class NearbySerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)
    radius_km = serializers.FloatField(min_value=0.1, max_value=50)
