"""Import a voter list (LEC) from the command line (same code as the "LEC" screen of the site admins).

    manage.py import_addresses LEC-communiquee-BERLIN-20260508-1347.xls --list "LEC Berlin" [--dry-run]
    manage.py import_addresses LEC-communiquee-BERLIN-20260508-1347.xls --organization demo-berlin   # its LEC

The consular list (.xls / .xlsx) is geocoded with the movement's Nominatim server for the list's country
(see canvassing/services/geocoding.py); a JSON file of geocoded entries is accepted too.
"""
import json
import pathlib

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Organization, VoterList
from canvassing.services import address_import


class Command(BaseCommand):
    help = "Import a voter list (consular list .xls/.xlsx, or JSON)."

    def add_arguments(self, parser):
        parser.add_argument("file")
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument("--list", help="Voter list: id or exact name")
        target.add_argument("--organization", "--org", help="Organization code: imports into the list it depends on")
        parser.add_argument("--dry-run", action="store_true", help="Only show what would change")

    def voter_list(self, opts) -> VoterList:
        if opts["list"]:
            key = opts["list"]
            found = VoterList.objects.filter(pk=int(key)) if key.isdigit() else VoterList.objects.filter(name=key)
            voter_list = found.first()
            if voter_list is None:
                raise CommandError(f"Unknown voter list '{key}'")
            return voter_list
        organization = Organization.objects.filter(code=opts["organization"]).select_related("voter_list").first()
        if organization is None:
            raise CommandError(f"Unknown organization '{opts['organization']}'")
        if organization.voter_list is None:
            raise CommandError(f"Organization '{organization.code}' does not depend on any voter list yet")
        return organization.voter_list

    def handle(self, *args, **opts):
        path = pathlib.Path(opts["file"])
        if not path.is_file():
            raise CommandError(f"File not found: {path}")
        voter_list = self.voter_list(opts)

        def progress(done, total):
            self.stdout.write(f"geocoded {done}/{total}")

        try:
            if opts["dry_run"]:
                report = address_import.preview(voter_list, path.read_bytes(), path.name)
            else:
                report = address_import.run_import(voter_list, path.read_bytes(), path.name, progress)
        except address_import.ImportFileError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(self.style.SUCCESS(json.dumps(report.as_dict(), ensure_ascii=False, indent=2)))
