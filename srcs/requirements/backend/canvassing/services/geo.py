"""Small geodesic helpers (pure Python, no heavy GIS dependency)."""
import math

LatLon = tuple[float, float]

EARTH_RADIUS_M = 6_371_008.8
WALKING_SPEED_MS = 5.0 / 3.6  # 5 km/h


def haversine_m(a: LatLon, b: LatLon) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def polyline_length_m(points: list[LatLon]) -> float:
    return sum(haversine_m(points[i], points[i + 1]) for i in range(len(points) - 1))


def haversine_matrix(points: list[LatLon]) -> list[list[float]]:
    n = len(points)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            matrix[i][j] = matrix[j][i] = haversine_m(points[i], points[j])
    return matrix


def bbox_around(points: list[LatLon], margin_km: float) -> tuple[float, float, float, float]:
    """Return (min_lon, min_lat, max_lon, max_lat) enclosing `points` plus a margin."""
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    dlat = margin_km / 111.32
    ref_lat = math.radians(max(abs(min(lats)), abs(max(lats))))
    dlon = margin_km / (111.32 * max(math.cos(ref_lat), 0.01))
    return min(lons) - dlon, min(lats) - dlat, max(lons) + dlon, max(lats) + dlat
