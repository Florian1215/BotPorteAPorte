"""Fill the database with fake addresses around Berlin for local development."""
import math
import random

from django.contrib.gis.geos import Point, Polygon
from django.core.management.base import BaseCommand

from accounts.models import Scope, User
from canvassing.models import Address, Area, semi_anonymize_name

CENTER = (52.5163, 13.4135)  # Berlin Mitte
STREETS = [
    "Torstr.", "Rosenthaler Str.", "Invalidenstr.", "Brunnenstr.", "Alte Schönhauser Str.", "Linienstr.",
    "Auguststr.", "Oranienburger Str.", "Karl-Marx-Allee", "Alexanderstr.", "Kastanienallee", "Schönhauser Allee",
    "Friedrichstr.", "Chausseestr.", "Wilhelmstr.", "Oranienstr.", "Adalbertstr.", "Skalitzer Str.",
]
FAMILY = ["Martin", "Bernard", "Dubois", "Thomas", "Robert", "Richard", "Petit", "Durand", "Leroy", "Moreau",
          "Simon", "Laurent", "Lefebvre", "Michel", "Garcia", "David", "Bertrand", "Roux", "Vincent", "Fournier"]
FIRST = ["Camille", "Léa", "Lucas", "Hugo", "Chloé", "Louis", "Emma", "Jules", "Inès", "Nathan", "Manon", "Adam"]


def hexagon(lat: float, lon: float, radius_km: float) -> Polygon:
    pts = []
    for k in range(7):
        angle = math.radians(60 * k)
        pts.append((lon + radius_km / (111.32 * math.cos(math.radians(lat))) * math.cos(angle),
                    lat + radius_km / 111.32 * math.sin(angle)))
    return Polygon(pts, srid=4326)


class Command(BaseCommand):
    help = "Create a demo scope with fake addresses, areas and a demo militant account (dev only)."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=800)
        parser.add_argument("--reset", action="store_true", help="Delete the demo scope first")

    def handle(self, *args, count, reset, **options):
        if reset:
            Scope.objects.filter(code="demo-berlin").delete()
        scope, _ = Scope.objects.get_or_create(
            code="demo-berlin", defaults={"name": "Démo Berlin", "country_code": "DE"}
        )
        rng = random.Random(42)
        addresses = []
        for _ in range(count):
            r_km = 3.5 * math.sqrt(rng.random())
            theta = rng.random() * 2 * math.pi
            lat = CENTER[0] + r_km / 111.32 * math.sin(theta)
            lon = CENTER[1] + r_km / (111.32 * math.cos(math.radians(CENTER[0]))) * math.cos(theta)
            addresses.append(
                Address(
                    scope=scope,
                    name=semi_anonymize_name(rng.choice(FAMILY)),
                    first_names=f"{rng.choice(FIRST)} {rng.choice(FIRST)}",
                    address=f"{rng.choice(STREETS)} {rng.randint(1, 180)}",
                    zip_code=rng.choice(["10115", "10119", "10178", "10243", "10405", "10997"]),
                    city="Berlin",
                    location=Point(lon, lat, srid=4326),
                )
            )
        Address.objects.bulk_create(addresses)

        if not scope.areas.exists():
            for name, (lat, lon), score in [
                ("Mitte — Rosenthaler Platz", (52.5296, 13.4013), 0.92),
                ("Prenzlauer Berg — Senefelderplatz", (52.5326, 13.4127), 0.81),
                ("Alexanderplatz", (52.5219, 13.4132), 0.64),
                ("Friedrichshain-Kreuzberg (Wahlbezirk 217)", (52.5030, 13.4180), 0.10),
            ]:
                Area.objects.create(scope=scope, name=name, score=score, geometry=hexagon(lat, lon, 0.6))

        user, created = User.objects.get_or_create(
            username="demo", defaults={"first_name": "Camarade", "scope": scope, "is_approved": True}
        )
        if created:
            user.set_password("demo-canvassing")
            user.save()
        for admin in User.objects.filter(is_superuser=True, scope__isnull=True):
            admin.scope = scope
            admin.save(update_fields=["scope"])

        self.stdout.write(self.style.SUCCESS(
            f"{count} addresses created in scope '{scope.code}'. Demo login: demo / demo-canvassing"
        ))
