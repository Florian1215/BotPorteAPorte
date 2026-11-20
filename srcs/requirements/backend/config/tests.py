from unittest import mock

from django.test import SimpleTestCase, override_settings

from config import map_tiles

WATERMARK = b"API KEY REQUIRED"


def fake_carto(valid_key):
    def tile(key):
        return b"real map" if key == valid_key else WATERMARK
    return tile


@override_settings(MAP_TILES="carto", CARTO_API_KEY="good-key", CARTO_TILE_URL="https://carto/{z}?key=good-key")
class MapTilesTests(SimpleTestCase):
    def setUp(self):
        map_tiles._cache.update(ok=None, until=0.0)

    def test_carto_by_default_with_osm_as_fallback(self):
        with mock.patch.object(map_tiles, "_carto_tile", fake_carto("good-key")):
            config = map_tiles.tile_config()
        self.assertEqual((config["provider"], config["fallback"]["tile_url"]), ("carto", "https://tile.openstreetmap.org/{z}/{x}/{y}.png"))

    def test_refused_key_switches_to_osm(self):
        with mock.patch.object(map_tiles, "_carto_tile", fake_carto("another-key")):
            self.assertEqual(map_tiles.tile_config()["provider"], "osm")

    def test_carto_unreachable_switches_to_osm(self):
        with mock.patch.object(map_tiles, "_carto_tile", side_effect=ConnectionError("down")):
            self.assertEqual(map_tiles.tile_config()["provider"], "osm")

    @override_settings(CARTO_API_KEY="")
    def test_no_key_uses_osm(self):
        self.assertEqual(map_tiles.tile_config()["provider"], "osm")
