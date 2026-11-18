"""Rebuild the neighbourhood outlines of the city packs without a polling-district map (Darmstadt, Dresden,
Warszawa) from OpenStreetMap, into `canvassing/data/pack_areas/` (kept in the repository)."""
from django.core.management.base import BaseCommand

from canvassing.services import packs


class Command(BaseCommand):
    help = "Download the neighbourhoods of the city packs from OpenStreetMap (Overpass)."

    def add_arguments(self, parser):
        parser.add_argument("cities", nargs="*", default=list(packs.AREA_QUERIES), help="darmstadt, dresden, warszawa")

    def handle(self, *args, **opts):
        for city in opts["cities"]:
            self.stdout.write(f"{city}: {packs.save_areas(city)} zones")
