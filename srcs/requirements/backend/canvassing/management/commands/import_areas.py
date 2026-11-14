"""Import predefined canvassing areas from a GeoJSON FeatureCollection."""
import json

from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Scope
from canvassing.models import Area


class Command(BaseCommand):
    help = "Import areas (polygons) from a GeoJSON file into a scope."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--scope", required=True)
        parser.add_argument("--name-property", default="name")
        parser.add_argument("--score-property", default="score")

    def handle(self, *args, **opts):
        try:
            scope = Scope.objects.get(code=opts["scope"])
        except Scope.DoesNotExist as exc:
            raise CommandError(f"Unknown scope '{opts['scope']}'") from exc
        with open(opts["file"], encoding="utf-8") as fh:
            collection = json.load(fh)

        n = 0
        for i, feature in enumerate(collection.get("features", []), start=1):
            props = feature.get("properties") or {}
            geometry = GEOSGeometry(json.dumps(feature["geometry"]), srid=4326)
            Area.objects.create(
                scope=scope,
                name=str(props.get(opts["name_property"]) or f"Zone {i}"),
                score=float(props.get(opts["score_property"]) or 0),
                geometry=geometry,
            )
            n += 1
        self.stdout.write(self.style.SUCCESS(f"{n} areas imported into '{scope.code}'."))
