"""Pedestrian routing through OpenRouteService, with a straight-line fallback (same strategy as the bot)."""
import logging
from dataclasses import dataclass

import requests
from django.conf import settings

from .geo import WALKING_SPEED_MS, LatLon, haversine_matrix, polyline_length_m

logger = logging.getLogger(__name__)

ORS_BASE_URL = "https://api.openrouteservice.org"
PROFILE = "foot-walking"
ORS_MAX_WAYPOINTS = 50
ORS_MAX_MATRIX_ELEMENTS = 3500
TIMEOUT_S = 20


@dataclass
class Route:
    geometry: list[LatLon]  # (lat, lon)
    distance_m: float
    duration_s: float
    approximate: bool


def _headers() -> dict:
    return {"Authorization": settings.ORS_TOKEN, "Content-Type": "application/json"}


def _ors_directions(points: list[LatLon]) -> Route | None:
    if not settings.ORS_TOKEN or len(points) < 2 or len(points) > ORS_MAX_WAYPOINTS:
        return None
    try:
        response = requests.post(
            f"{ORS_BASE_URL}/v2/directions/{PROFILE}/geojson",
            json={"coordinates": [[lon, lat] for lat, lon in points]},
            headers=_headers(),
            timeout=TIMEOUT_S,
        )
        response.raise_for_status()
        feature = response.json()["features"][0]
        summary = feature["properties"].get("summary", {})
        geometry = [(lat, lon) for lon, lat, *_ in feature["geometry"]["coordinates"]]
        return Route(
            geometry=geometry,
            distance_m=float(summary.get("distance", polyline_length_m(geometry))),
            duration_s=float(summary.get("duration", 0.0)),
            approximate=False,
        )
    except Exception as exc:  # rate limit, network, bad input... -> beeline fallback
        logger.warning("ORS directions failed, falling back to beeline: %s", exc)
        return None


def beeline(points: list[LatLon]) -> Route:
    distance = polyline_length_m(points)
    return Route(geometry=list(points), distance_m=distance, duration_s=distance / WALKING_SPEED_MS, approximate=True)


def route_through(points: list[LatLon]) -> Route:
    """Walking route visiting `points` in order."""
    return _ors_directions(points) or beeline(points)


def distance_matrix(points: list[LatLon]) -> list[list[float]]:
    """Walking distances between all pairs of points (meters). Falls back to great-circle distances."""
    if settings.ORS_TOKEN and 2 <= len(points) and len(points) ** 2 <= ORS_MAX_MATRIX_ELEMENTS:
        try:
            response = requests.post(
                f"{ORS_BASE_URL}/v2/matrix/{PROFILE}",
                json={"locations": [[lon, lat] for lat, lon in points], "metrics": ["distance"]},
                headers=_headers(),
                timeout=TIMEOUT_S,
            )
            response.raise_for_status()
            distances = response.json()["distances"]
            fallback = None
            for i, row in enumerate(distances):
                for j, value in enumerate(row):
                    if value is None:  # unroutable pair
                        fallback = fallback or haversine_matrix(points)
                        row[j] = fallback[i][j]
            return distances
        except Exception as exc:
            logger.warning("ORS matrix failed, falling back to great-circle distances: %s", exc)
    return haversine_matrix(points)
