from django.contrib.gis.geos import Point, Polygon
from django.db.models import BooleanField, Count
from django.db.models.expressions import RawSQL
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsCanvasser

from .addressutils import AddressNotGeolocated, split_postcode_city, split_street_name_number
from .models import SUCCESS_RESULTS, Address, Area, Status, Tour, Visit, VisitResult
from .serializers import (
    CreateTourSerializer,
    ManualGeocodeSerializer,
    ManualMarkSerializer,
    ManualSearchSerializer,
    NearbySerializer,
    ResultSerializer,
    address_to_dict,
    area_to_dict,
    tour_to_dict,
)
from .services import geocoding
from .services import tours as tour_service
from .services.geo import bbox_around

NEARBY_LIMIT = 3000
TOP_AREAS = 10


def error(message: str, code: int = status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"detail": message}, status=code)


class CanvasserView(APIView):
    permission_classes = [IsCanvasser]

    def handle_exception(self, exc):
        if isinstance(exc, tour_service.TourError):
            return error(exc.message, exc.status_code)
        return super().handle_exception(exc)


# --------------------------------------------------------------------------- tours


class TourListView(CanvasserView):
    def post(self, request):
        """Prepare a tour (draft): select and order addresses, compute the route."""
        tour_service.expire_stale_tours()
        serializer = CreateTourSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["kind"] == Tour.Kind.FREE:
            tour = tour_service.prepare_free_tour(request.user, data["start"], data["end"], data["radius_km"])
        else:
            area = get_object_or_404(Area, pk=data["area_id"], scope_id=request.user.scope_id)
            tour = tour_service.prepare_predefined_tour(request.user, area, data["start"])
        return Response(tour_to_dict(tour), status=status.HTTP_201_CREATED)


class CurrentTourView(CanvasserView):
    def get(self, request):
        tour_service.expire_stale_tours()
        tour = tour_service.current_tour(request.user)
        return Response(tour_to_dict(tour) if tour else None)


class TourMixin:
    def get_tour(self, request, pk) -> Tour:
        return get_object_or_404(Tour.objects.select_related("area"), pk=pk, user=request.user)


class TourDetailView(TourMixin, CanvasserView):
    def get(self, request, pk):
        return Response(tour_to_dict(self.get_tour(request, pk)))

    def delete(self, request, pk):
        """Cancel a draft (the bot's "Annuler" before "Démarrer tournée")."""
        tour = self.get_tour(request, pk)
        if tour.status != Tour.TourStatus.DRAFT:
            return error("Seule une tournée non démarrée peut être annulée.", status.HTTP_409_CONFLICT)
        tour.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TourStartView(TourMixin, CanvasserView):
    def post(self, request, pk):
        tour = tour_service.start_tour(self.get_tour(request, pk))
        return Response(tour_to_dict(tour))


class TourFinishView(TourMixin, CanvasserView):
    def post(self, request, pk):
        tour = tour_service.finish_tour(self.get_tour(request, pk))
        return Response(tour_to_dict(tour))


class StopResultView(TourMixin, CanvasserView):
    def post(self, request, pk, stop_id):
        tour = self.get_tour(request, pk)
        stop = get_object_or_404(tour.stops.select_related("address"), pk=stop_id)
        serializer = ResultSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tour_service.record_stop_result(tour, stop, serializer.validated_data["result"])
        return Response(tour_to_dict(tour))


# --------------------------------------------------------------------------- areas & addresses


class AreaListView(CanvasserView):
    def get(self, request):
        """Top predefined areas of the user's scope, by score (like the bot)."""
        areas = Area.objects.filter(scope_id=request.user.scope_id).order_by("-score")[:TOP_AREAS]
        result = []
        for area in areas:
            n = Address.objects.filter(
                scope_id=request.user.scope_id, status=Status.TO_VISIT, location__within=area.geometry
            ).count()
            result.append(area_to_dict(area, n_to_visit=n))
        return Response(result)


class NearbyAddressesView(CanvasserView):
    def get(self, request):
        """Addresses still to visit around a point (the bot's /adresses_alentours)."""
        serializer = NearbySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        lat, lon, radius_km = (serializer.validated_data[k] for k in ("lat", "lon", "radius_km"))
        bbox = Polygon.from_bbox(bbox_around([(lat, lon)], radius_km))
        qs = (
            Address.objects.filter(scope_id=request.user.scope_id, status=Status.TO_VISIT, location__within=bbox)
            .alias(
                near=RawSQL(
                    "ST_DWithin(location::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)",
                    (lon, lat, radius_km * 1000),
                    output_field=BooleanField(),
                )
            )
            .filter(near=True)
        )
        total = qs.count()
        addresses = [address_to_dict(a, with_names=False) for a in qs[:NEARBY_LIMIT]]
        return Response({"total": total, "truncated": total > len(addresses), "addresses": addresses})


# --------------------------------------------------------------------------- manual marking


class ManualGeocodeView(CanvasserView):
    def post(self, request):
        serializer = ManualGeocodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        country = request.user.scope.country_code
        street_name, street_number = split_street_name_number(serializer.validated_data["street"], country_code=country)
        zip_str, city = split_postcode_city(serializer.validated_data["postcode_city"])
        if zip_str is None:
            return error("Code postal et ville invalides. Exemple : 10115 Berlin")
        parsed = AddressNotGeolocated("", "", street_name, street_number, zip_str, city)
        try:
            location = geocoding.geocode(parsed, country)
        except Exception:
            return error("Le service de géocodage est indisponible, réessaie dans un instant.", 503)
        fields = geocoding.location_to_fields(parsed, location) if location else None
        if fields is None:
            return error("L'adresse n'a pas pu être géocodée, merci de vérifier le formatage.", 404)
        return Response(fields)


class ManualSearchView(CanvasserView):
    def post(self, request):
        """Find the addresses to visit matching street address, zip, city and the first 3 letters of the name."""
        serializer = ManualSearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        matches = Address.objects.filter(
            scope_id=request.user.scope_id,
            status=Status.TO_VISIT,
            address__istartswith=data["address"],
            zip_code=data["zip_code"],
            city__iexact=data["city"],
            name__istartswith=data["name"][:3],
        )[:50]
        return Response([address_to_dict(a) for a in matches])


class ManualMarkView(CanvasserView):
    def post(self, request):
        serializer = ManualMarkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        addresses = list(
            Address.objects.filter(
                scope_id=request.user.scope_id,
                status=Status.TO_VISIT,
                id__in=serializer.validated_data["address_ids"],
            )
        )
        if not addresses:
            return error("Ces adresses ont déjà été visitées ou sont en cours de visite.", status.HTTP_409_CONFLICT)
        tour_service.apply_result(request.user, addresses, serializer.validated_data["result"])
        return Response({"marked": len(addresses)})


# --------------------------------------------------------------------------- stats


class MyStatsView(CanvasserView):
    def get(self, request):
        counts = dict(
            Visit.objects.filter(user=request.user).values_list("result").annotate(n=Count("id")).order_by()
        )
        by_result = {r.value: counts.get(r.value, 0) for r in VisitResult}
        return Response(
            {
                "total_success": sum(by_result[r.value] for r in SUCCESS_RESULTS),
                "total_visits": sum(by_result.values()),
                "by_result": by_result,
                "tours_completed": Tour.objects.filter(user=request.user, status=Tour.TourStatus.COMPLETED).count(),
            }
        )


class ScopeOverviewView(CanvasserView):
    def get(self, request):
        """Progress of the whole scope (shown on the home page)."""
        counts = dict(
            Address.objects.filter(scope_id=request.user.scope_id)
            .values_list("status")
            .annotate(n=Count("id"))
            .order_by()
        )
        return Response(
            {
                "total": sum(counts.values()),
                "by_status": {s.name.lower(): counts.get(s.value, 0) for s in Status},
            }
        )
