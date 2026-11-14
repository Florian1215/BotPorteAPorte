"""Geocode a consulate voter list (XLS/XLSX) into the database. Port of the bot's `excelimport.py`.

Expected columns: family_name, usage_name, first_names, street_name_number, postcode_city
"""
import pathlib

import pandas as pd
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Scope
from canvassing.addressutils import sanitize_address
from canvassing.models import Address, semi_anonymize_name
from canvassing.services import geocoding

REQUIRED_WITH_DATA = ["street_name_number", "postcode_city"]
REQUIRED_COLUMNS = REQUIRED_WITH_DATA + ["family_name", "usage_name", "first_names"]

NOMINATIM_SERVERS = {
    "DE": "nominatimdeutschland.okras.eu:443",
    "AT": "nominatimaustria.okras.eu:443",
    "CZ": "nominatimczechia.okras.eu:443",
    "FR": "nominatimfrance.okras.eu:443",
    "LU": "nominatimluxemburg.okras.eu:443",
}


class Command(BaseCommand):
    help = "Import and geocode an address spreadsheet into a scope."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Path to the XLS/XLSX file (e.g. liste_berlin_DE.xlsx)")
        parser.add_argument("--scope", required=True, help="Scope code (created if missing)")
        parser.add_argument("--scope-name", help="Human-readable scope name when creating it")
        parser.add_argument("--country", help="ISO country code. Default: last 2 chars of the filename")
        parser.add_argument("--server", help="Custom Nominatim server, e.g. nominatimdeutschland.okras.eu:443")
        parser.add_argument("--use-okras", action="store_true", help="Use the okras.eu Nominatim server for the country")
        parser.add_argument("--delay", type=float, default=1.0, help="Min delay between geocoding requests (s)")
        parser.add_argument("--cities", nargs="+", default=[], help="Keep only these cities (case insensitive)")

    def handle(self, *args, **opts):
        path = pathlib.Path(opts["file"])
        if not path.is_file():
            raise CommandError(f"File not found: {path}")
        country = (opts["country"] or path.stem[-2:]).upper()
        server = opts["server"] or (NOMINATIM_SERVERS.get(country) if opts["use_okras"] else None)
        cities = {c.strip().lower() for c in opts["cities"]}

        scope, created = Scope.objects.get_or_create(
            code=opts["scope"], defaults={"name": opts["scope_name"] or opts["scope"], "country_code": country}
        )
        if created:
            self.stdout.write(f"Scope '{scope.code}' created.")

        df = pd.read_excel(path)
        if not set(REQUIRED_COLUMNS) <= set(df.columns):
            raise CommandError(f"The spreadsheet must contain the columns: {REQUIRED_COLUMNS}")

        geocoder = geocoding.make_geocoder(domain=server, min_delay_seconds=opts["delay"])
        stats = dict(insufficient=0, invalid=0, wrong_city=0, geoloc_fail=0, success=0)
        batch: list[Address] = []

        for i, (_, row) in enumerate(df.iterrows(), start=1):
            if any(str(row[c]).lower().strip() == "nan" for c in REQUIRED_WITH_DATA):
                stats["insufficient"] += 1
                continue
            parsed = sanitize_address(address_row=row, country_code=country)
            if parsed is None:
                stats["invalid"] += 1
                continue
            if cities and parsed.city.lower() not in cities:
                stats["wrong_city"] += 1
                continue
            try:
                location = geocoding.geocode(parsed, country, geocoder=geocoder)
            except Exception as exc:
                self.stderr.write(f"Geocoding error on row {i}: {exc}")
                location = None
            fields = geocoding.location_to_fields(parsed, location) if location else None
            if fields is None:
                self.stderr.write(f"Could not geocode: {parsed.to_str()}")
                stats["geoloc_fail"] += 1
                continue
            batch.append(
                Address(
                    scope=scope,
                    name=semi_anonymize_name(parsed.usage_name),
                    first_names=parsed.first_names,
                    address=fields["address"],
                    zip_code=fields["zip_code"],
                    city=fields["city"],
                    location=Point(fields["lon"], fields["lat"], srid=4326),
                )
            )
            stats["success"] += 1
            if len(batch) >= 200:
                Address.objects.bulk_create(batch)
                batch.clear()
            if i % 100 == 0:
                self.stdout.write(f"{i}/{len(df)} rows processed...")

        Address.objects.bulk_create(batch)
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(df)} rows processed\n"
                f"{stats['insufficient']} skipped: missing data\n"
                f"{stats['invalid']} skipped: invalid address format\n"
                f"{stats['wrong_city']} skipped: not in {sorted(cities) or 'the selected cities'}\n"
                f"{stats['geoloc_fail']} could not be geocoded (typos?)\n"
                f"{stats['success']} imported into scope '{scope.code}'"
            )
        )
