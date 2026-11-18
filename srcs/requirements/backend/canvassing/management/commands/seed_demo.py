"""Fill the database with fake addresses around Berlin for local development."""
import math
import random

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand

from accounts.models import Organization, VoterList, Role, User
from canvassing.models import Address

CENTER = (52.5163, 13.4135)  # Berlin Mitte
STREETS = [
    "Torstr.", "Rosenthaler Str.", "Invalidenstr.", "Brunnenstr.", "Alte Schönhauser Str.", "Linienstr.",
    "Auguststr.", "Oranienburger Str.", "Karl-Marx-Allee", "Alexanderstr.", "Kastanienallee", "Schönhauser Allee",
    "Friedrichstr.", "Chausseestr.", "Wilhelmstr.", "Oranienstr.", "Adalbertstr.", "Skalitzer Str.",
]
FAMILY = ["Martin", "Bernard", "Dubois", "Thomas", "Robert", "Richard", "Petit", "Durand", "Leroy", "Moreau",
          "Simon", "Laurent", "Lefebvre", "Michel", "Garcia", "David", "Bertrand", "Roux", "Vincent", "Fournier"]
FIRST = ["Camille", "Léa", "Lucas", "Hugo", "Chloé", "Louis", "Emma", "Jules", "Inès", "Nathan", "Manon", "Adam"]


class Command(BaseCommand):
    help = "Create a demo organization with fake addresses and a demo militant account (dev only)."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=800)
        parser.add_argument("--reset", action="store_true", help="Delete the demo organization first")

    def handle(self, *args, count, reset, **options):
        if reset:
            Organization.objects.filter(code="demo-berlin").delete()
            VoterList.objects.filter(name="LEC Démo Berlin").delete()
        voter_list, _ = VoterList.objects.get_or_create(name="LEC Démo Berlin", defaults={"country_code": "DE"})
        organization, _ = Organization.objects.get_or_create(
            code="demo-berlin",
            defaults={
                "name": "Démo Berlin",
                "country_code": "DE",
                "city": "Berlin",
                "city_lat": 52.5170,
                "city_lon": 13.3889,
                "voter_list": voter_list,
            },
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
                    voter_list=voter_list,
                    name=rng.choice(FAMILY),
                    first_names=f"{rng.choice(FIRST)} {rng.choice(FIRST)}",
                    address=f"{rng.choice(STREETS)} {rng.randint(1, 180)}",
                    zip_code=rng.choice(["10115", "10119", "10178", "10243", "10405", "10997"]),
                    city="Berlin",
                    location=Point(lon, lat, srid=4326),
                )
            )
        for a in addresses:
            a.source_key = a.compute_key()
        Address.objects.bulk_create(addresses)

        # One account per role, plus a sign-up waiting for approval. No password: in development the login
        # code is printed in the backend logs (make logs SERVICE=backend).
        for email, first_name, role, approved in [
            ("militant@demo.test", "Camarade", Role.MILITANT, True),
            ("aguerri@demo.test", "Alex", Role.EXPERIENCED, True),
            ("responsable@demo.test", "Sam", Role.MANAGER, True),
            ("nouveau@demo.test", "Dominique", Role.MILITANT, False),
        ]:
            User.objects.get_or_create(
                email=email,
                defaults={"first_name": first_name, "organization": organization, "role": role, "is_approved": approved},
            )
        for admin in User.objects.filter(is_superuser=True, organization__isnull=True):
            admin.organization = organization
            admin.save(update_fields=["organization"])

        self.stdout.write(self.style.SUCCESS(
            f"{count} addresses created in organization '{organization.code}'. "
            "Demo logins (code in the backend logs): militant@ / aguerri@ / responsable@ / nouveau@demo.test (pending)"
        ))
