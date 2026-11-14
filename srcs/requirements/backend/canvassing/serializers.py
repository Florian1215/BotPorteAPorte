import json

from rest_framework import serializers

from .models import Address, Area, Tour, TourStop, VisitResult


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
        data["name"] = address.display_name
        data["first_name"] = address.first_name
    return data


def area_to_dict(area: Area, n_to_visit: int | None = None) -> dict:
    data = {"id": area.id, "name": area.name, "score": area.score, "geometry": json.loads(area.geometry.geojson)}
    if n_to_visit is not None:
        data["n_to_visit"] = n_to_visit
    return data


def stop_to_dict(stop: TourStop) -> dict:
    return {
        "id": stop.id,
        "position": stop.position,
        "result": stop.result or None,
        "visited_at": stop.visited_at,
        "address": address_to_dict(stop.address),
    }


def tour_to_dict(tour: Tour) -> dict:
    from .services.tours import tour_summary

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
        "stops": [stop_to_dict(s) for s in tour.stops.select_related("address")],
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


class ResultSerializer(serializers.Serializer):
    result = serializers.ChoiceField(choices=VisitResult.choices)


class NearbySerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)
    radius_km = serializers.FloatField(min_value=0.1, max_value=50)


class ManualGeocodeSerializer(serializers.Serializer):
    street = serializers.CharField(max_length=255)
    postcode_city = serializers.CharField(max_length=255)


class ManualSearchSerializer(serializers.Serializer):
    address = serializers.CharField(max_length=255)
    zip_code = serializers.CharField(max_length=16)
    city = serializers.CharField(max_length=128)
    name = serializers.CharField(min_length=3, max_length=255)


class ManualMarkSerializer(serializers.Serializer):
    address_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1, max_length=50)
    result = serializers.ChoiceField(choices=VisitResult.choices)
