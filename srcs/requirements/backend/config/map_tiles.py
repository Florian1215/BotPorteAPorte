"""Which basemap the frontend gets: CARTO Voyager by default, OpenStreetMap's tiles when CARTO does not work.

CARTO never answers a refused key with an error: it sends HTTP 200 and a tile reading "API KEY REQUIRED". So the
server fetches one tile with our key and one with a key that surely is invalid: identical images mean our key is
refused (missing, mistyped, expired, over quota). That, or CARTO unreachable, switches the site to OpenStreetMap.
The answer is cached (CHECK_TTL when CARTO works, RETRY_TTL when it does not, so that it comes back by itself).
"""
import logging
import threading
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

PROBE_TILE = (12, 2200, 1343)  # any tile works: the "API KEY REQUIRED" image is the same everywhere
CHECK_TTL = 6 * 3600
RETRY_TTL = 10 * 60
INVALID_KEY = "invalid-key-check"

_lock = threading.Lock()
_cache: dict = {"ok": None, "until": 0.0}


def _carto_tile(key: str) -> bytes:
    z, x, y = PROBE_TILE
    response = requests.get(
        f"https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
        params={"key": key},
        headers={"User-Agent": "canvassing-web (basemap check)"},
        timeout=5,
    )
    response.raise_for_status()
    if not response.headers.get("Content-Type", "").startswith("image/"):
        raise ValueError(f"not an image: {response.headers.get('Content-Type')}")
    return response.content


def carto_works() -> bool:
    """Is CARTO serving real tiles for our key? (cached)"""
    now = time.monotonic()
    if _cache["ok"] is not None and now < _cache["until"]:
        return _cache["ok"]
    with _lock:
        if _cache["ok"] is not None and now < _cache["until"]:
            return _cache["ok"]
        if not settings.CARTO_API_KEY:
            ok, reason = False, "CARTO_API_KEY is empty"
        else:
            try:
                ok = _carto_tile(settings.CARTO_API_KEY) != _carto_tile(INVALID_KEY)
                reason = "" if ok else "key refused (CARTO answers 'API KEY REQUIRED')"
            except Exception as exc:  # network error, CARTO down
                ok, reason = False, f"CARTO unreachable: {exc}"
        if not ok:
            logger.warning("Map tiles: %s, using OpenStreetMap", reason)
        _cache.update(ok=ok, until=time.monotonic() + (CHECK_TTL if ok else RETRY_TTL))
        return ok


def tile_config() -> dict:
    """The basemap sent to the frontend, with OpenStreetMap as `fallback` (used by the browser if CARTO tiles fail)."""
    osm = {"tile_url": settings.OSM_TILE_URL, "attribution": settings.OSM_ATTRIBUTION}
    if settings.MAP_TILES == "osm" or not carto_works():
        return {**osm, "provider": "osm", "fallback": None}
    return {"tile_url": settings.CARTO_TILE_URL, "attribution": settings.CARTO_ATTRIBUTION, "provider": "carto", "fallback": osm}
