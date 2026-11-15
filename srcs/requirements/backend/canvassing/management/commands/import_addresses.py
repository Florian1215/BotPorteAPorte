"""Import an organization's voter list from the command line (same code as the organization settings screen).

    manage.py import_addresses LEC-communiquee-BERLIN-20260508-1347.xls --organization demo-berlin [--dry-run]

The consular list (.xls / .xlsx) is geocoded with the movement's Nominatim server for the organization's country
(see canvassing/services/geocoding.py); a JSON file of geocoded entries is accepted too.
"""
import json
import pathlib

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Organization
from canvassing.services import address_import


class Command(BaseCommand):
    help = "Import an organization's voter list (consular list .xls/.xlsx, or JSON)."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--organization", "--org", required=True, help="Organization code")
        parser.add_argument("--dry-run", action="store_true", help="Only show what would change")

    def handle(self, *args, **opts):
        path = pathlib.Path(opts["file"])
        if not path.is_file():
            raise CommandError(f"File not found: {path}")
        try:
            organization = Organization.objects.get(code=opts["organization"])
        except Organization.DoesNotExist:
            raise CommandError(f"Unknown organization '{opts['organization']}'") from None

        def progress(done, total):
            self.stdout.write(f"geocoded {done}/{total}")

        try:
            if opts["dry_run"]:
                report = address_import.preview(organization, path.read_bytes(), path.name)
            else:
                report = address_import.run_import(organization, path.read_bytes(), path.name, progress)
        except address_import.ImportFileError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(self.style.SUCCESS(json.dumps(report.as_dict(), ensure_ascii=False, indent=2)))
