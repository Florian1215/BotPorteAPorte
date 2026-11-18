"""Import the database of the Telegram bot (a `pg_dump` .sql file) into the site.

    manage.py import_bot_db postgres-20260824.sql [--dry-run] [--org BERLIN=demo-berlin] [--election "…"]

What is imported, from the bot's `address` table:
- every address, into the voter list (LEC) of the organization of its consulate (BERLIN, WIEN, …). Organizations
  are found by their city or name (Berlin → "Berlin Insoumise", Wien → "Vienne Insoumise"…) and created when
  missing, with a list of their own when they have none ("LEC Berlin"); `--org` forces one;
- the result of the last visit of each address (the bot kept no history), as a visit of the election given by
  `--election` (default: the consular election of May 2026), dated with the bot's `visit_planned_at`, with the
  Telegram id of who made it (`visit_planned_by`): it becomes theirs once they link their Telegram account on the
  site (Mon compte), or right away if they already did.

The file is read as text: it does not need to be restored in PostgreSQL. Addresses already on the site (same
person at the same address) and duplicates inside the file are only added once. Running the command again
adds nothing new (but fills in the Telegram id of visits imported before it was kept). The bot's areas (hand-drawn zones) are not imported: zones are now the polling districts.
"""
import pathlib
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone as dt_timezone

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from accounts.models import Organization, User, VoterList
from canvassing.models import RESULT_TO_STATUS, AbsentDetail, Address, Election, Status, Visit, VisitResult, address_key
from canvassing.services.address_import import person_key
from canvassing.services.elections import RESET_STATUSES

DEFAULT_ELECTION = "Élection consulaire 2026"

# Consulate of the bot → (city, country, names an organization may have, name of a new organization).
CONSULATES = {
    "BERLIN": ("Berlin", "DE", ["berlin"], "Berlin Insoumise"),
    "MÜNCHEN": ("München", "DE", ["münchen", "munchen", "muenchen", "munich"], "Munich Insoumise"),
    "STUTTGART": ("Stuttgart", "DE", ["stuttgart"], "Stuttgart Insoumise"),
    "WIEN": ("Wien", "AT", ["wien", "vienne", "vienna"], "Vienne Insoumise"),
    "HAMBURG": ("Hamburg", "DE", ["hamburg", "hambourg"], "Hambourg Insoumise"),
}

# Bot status → visit result (+ detail). 3 and 7 come from the last version of the bot.
STATUS_RESULTS = {
    "2": (VisitResult.ADDRESS_FAILURE, ""),
    "3": (VisitResult.ADDRESS_TO_RETRY, ""),
    "4": (VisitResult.COMMITMENT_TO_VOTE, ""),
    "5": (VisitResult.GOOD_CONVERSATION, ""),
    "6": (VisitResult.DO_NOT_CONTACT, ""),
    "7": (VisitResult.ADDRESS_TO_RETRY, AbsentDetail.LEAFLET),
}

ADDRESS_COLUMNS = [
    "id", "consulat", "usage_name", "first_name", "address", "zip_code", "city", "lat", "lon", "n_visits", "status",
    "visit_planned_at", "visit_planned_by", "family_name",
]

_ESCAPE = re.compile(r"\\(\\|[btnrfv]|[0-7]{1,3})")
_ESCAPES = {"\\": "\\", "b": "\b", "t": "\t", "n": "\n", "r": "\r", "f": "\f", "v": "\v"}


def decode(field: str) -> str | None:
    """One field of a PostgreSQL COPY text line."""
    if field == r"\N":
        return None
    return _ESCAPE.sub(lambda m: _ESCAPES.get(m.group(1)) or chr(int(m.group(1), 8)), field)


def read_addresses(path: pathlib.Path):
    """Rows of the bot's `address` table, as dicts."""
    with path.open(encoding="utf-8") as fh:
        columns = None
        for line in fh:
            if line.startswith("COPY public.address "):
                columns = [c.strip().strip('"') for c in line[line.index("(") + 1 : line.index(")")].split(",")]
                break
        if columns is None:
            raise CommandError("Table « address » introuvable : est-ce bien la sauvegarde de la base du bot ?")
        missing = set(ADDRESS_COLUMNS) - set(columns)
        if missing:
            raise CommandError(f"Colonnes manquantes dans la table address : {', '.join(sorted(missing))}")
        for line in fh:
            if line.startswith("\\."):
                return
            yield dict(zip(columns, (decode(f) for f in line.rstrip("\n").split("\t"))))


def visit_of(row: dict) -> tuple[str, str, datetime, int | None] | None:
    """(result, detail, date, Telegram id of who made it) of the last visit of a bot address, or None if never visited."""
    when = row.get("visit_planned_at")
    if not when:
        return None
    if row.get("status") in STATUS_RESULTS:
        result, detail = STATUS_RESULTS[row["status"]]
    elif int(row.get("n_visits") or 0) > 0:
        # Visited but no status: in the bot, "absent" put the address back to "to visit".
        result, detail = VisitResult.ADDRESS_TO_RETRY, ""
    else:
        return None  # only planned (tour never finished)
    date = datetime.fromisoformat(when)
    if date.tzinfo is None:
        date = date.replace(tzinfo=dt_timezone.utc)
    by = str(row.get("visit_planned_by") or "").strip()
    return result, detail, date, int(by) if by.lstrip("-").isdigit() else None


def status_after(result: str, election_is_current: bool) -> int:
    status = RESULT_TO_STATUS[VisitResult(result)]
    if not election_is_current and status in RESET_STATUSES:
        return Status.TO_VISIT  # a promise for a past election: to visit again for the current one
    return status


class Command(BaseCommand):
    help = "Import the Telegram bot's database (pg_dump .sql file): addresses and the result of their last visit."

    def add_arguments(self, parser):
        parser.add_argument("file", help="pg_dump of the bot's database, e.g. postgres-20260824.sql")
        parser.add_argument("--org", action="append", default=[], metavar="CONSULAT=code",
                            help="Organization for a consulate, e.g. --org BERLIN=demo-berlin (repeatable)")
        parser.add_argument("--election", default=DEFAULT_ELECTION, help=f"Election of the visits (default: {DEFAULT_ELECTION})")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be imported, change nothing")

    def handle(self, *args, **opts):
        path = pathlib.Path(opts["file"])
        if not path.is_file():
            raise CommandError(f"Fichier introuvable : {path}")
        forced = {}
        for item in opts["org"]:
            consulate, _, code = item.partition("=")
            if not code:
                raise CommandError(f"--org attend CONSULAT=code (reçu : {item})")
            try:
                forced[consulate.strip().upper()] = Organization.objects.get(code=code.strip())
            except Organization.DoesNotExist:
                raise CommandError(f"Organisation inconnue : {code}") from None

        rows_by_consulate: dict[str, list[dict]] = defaultdict(list)
        for row in read_addresses(path):
            rows_by_consulate[(row.get("consulat") or "").strip().upper()].append(row)
        if not rows_by_consulate:
            raise CommandError("Aucune adresse dans ce fichier.")

        with transaction.atomic():
            election, created = Election.objects.get_or_create(name=opts["election"])
            if created and not Election.objects.filter(is_current=True).exists():
                election.is_current = True
                election.save(update_fields=["is_current"])
            totals = Counter()
            lines = []
            for consulate, rows in sorted(rows_by_consulate.items()):
                organization, new_org = self.organization_for(consulate, forced)
                stats = self.import_consulate(organization, rows, election)
                totals.update(stats)
                lines.append((consulate, organization, new_org, stats))
            self.report(path, election, lines, totals, opts["dry_run"])
            if opts["dry_run"]:
                transaction.set_rollback(True)

    # ----------------------------------------------------------------------------------------------- organizations

    def organization_for(self, consulate: str, forced: dict) -> tuple[Organization, bool]:
        if consulate in forced:
            return forced[consulate], False
        city, country, aliases, new_name = CONSULATES.get(consulate, (consulate.title(), "DE", [consulate.lower()], f"{consulate.title()} Insoumise"))
        candidates = [
            o for o in Organization.objects.all()
            if any(a in (o.city or "").lower() or a in o.name.lower() or a in o.code.lower() for a in aliases)
        ]
        if candidates:
            # Several (e.g. a demo one): the one that already has the most addresses.
            return max(
                candidates,
                key=lambda o: Address.all_objects.filter(voter_list_id=o.voter_list_id).count() if o.voter_list_id else -1,
            ), False
        code = slugify(new_name)
        organization, created = Organization.objects.get_or_create(
            code=code, defaults={"name": new_name, "city": city, "country_code": country}
        )
        return organization, created

    # ----------------------------------------------------------------------------------------------- addresses

    def voter_list_of(self, organization: Organization) -> VoterList:
        """The list the organization depends on (created, named after its city, when it has none)."""
        if organization.voter_list_id is None:
            organization.voter_list = VoterList.objects.create(
                name=f"LEC {organization.city or organization.name}", country_code=organization.country_code
            )
            organization.save(update_fields=["voter_list"])
        return organization.voter_list

    def import_consulate(self, organization: Organization, rows: list[dict], election: Election) -> Counter:
        stats = Counter(lus=len(rows))
        voter_list = self.voter_list_of(organization)

        # Duplicates inside the file: same person (full name) at the same address → one address, the most
        # recent visit. `_key` (the site's key, on a shortened name) is only used to find addresses already there.
        unique: dict[tuple, dict] = {}
        for row in rows:
            name = (row.get("usage_name") or row.get("family_name") or "").strip()
            row["_name"] = name
            row["_first"] = (row.get("first_name") or "").strip()
            row["_key"] = address_key(name, row["_first"], row["address"] or "", row["zip_code"] or "", row["city"] or "")
            row["_visit"] = visit_of(row)
            same = tuple(" ".join(str(row.get(c) or "").lower().split()) for c in ("usage_name", "family_name", "first_name", "address", "zip_code", "city"))
            kept = unique.get(same)
            if kept is None:
                unique[same] = row
                continue
            stats["doublons_fichier"] += 1
            if row["_visit"] and (not kept["_visit"] or row["_visit"][2] > kept["_visit"][2]):
                unique[same] = row

        # Already on the site (imported from a list, or a previous run of this command).
        existing = list(Address.all_objects.filter(voter_list=voter_list))
        by_key = {a.source_key: a for a in existing}
        by_key.update({a.compute_key(): a for a in existing})
        by_person = defaultdict(list)
        for a in existing:
            by_person[person_key(a.name, a.first_names, a.zip_code)].append(a)
        known_visits = {
            (address_id, result, created_at): (pk, telegram_user_id)
            for pk, address_id, result, created_at, telegram_user_id in Visit.objects.filter(
                address__voter_list=voter_list
            ).values_list("id", "address_id", "result", "created_at", "telegram_user_id")
        }
        members = dict(User.objects.filter(telegram_id__isnull=False).values_list("telegram_id", "id"))
        authors: dict[int, int] = {}  # visit already imported, without its Telegram id → Telegram id

        to_create: list[Address] = []
        new_visits: list[tuple[Address, tuple]] = []
        to_update: list[Address] = []
        for row in unique.values():
            match = by_key.get(row["_key"]) or next(iter(by_person.get(person_key(row["_name"], row["_first"], row["zip_code"] or ""), [])), None)
            visit = row["_visit"]
            if match is not None:
                stats["deja_en_base"] += 1
                known = known_visits.get((match.id, visit[0], visit[2])) if visit else None
                if known is not None and known[1] is None and visit[3] is not None:
                    authors[known[0]] = visit[3]
                if visit and known is None:
                    new_visits.append((match, visit))
                    # Only fill in an address nobody visited on the site since.
                    if match.status == Status.TO_VISIT:
                        status = status_after(visit[0], election.is_current)
                        if status != match.status:
                            match.status = status
                            to_update.append(match)
                continue
            try:
                lat, lon = float(row["lat"]), float(row["lon"])
            except (TypeError, ValueError):
                stats["invalides"] += 1
                continue
            address = Address(
                voter_list=voter_list,
                name=row["_name"][:255],
                first_names=row["_first"][:255],
                address=(row["address"] or "")[:255],
                zip_code=(row["zip_code"] or "")[:16],
                city=(row["city"] or "")[:128],
                location=Point(lon, lat, srid=4326),
                source_key=row["_key"],
                status=status_after(visit[0], election.is_current) if visit else Status.TO_VISIT,
                visit_planned_at=visit[2] if visit else None,
            )
            to_create.append(address)
            if visit:
                new_visits.append((address, visit))
            stats["nouvelles"] += 1

        Address.all_objects.bulk_create(to_create, batch_size=1000)
        Address.all_objects.bulk_update(to_update, ["status"], batch_size=1000)
        Visit.objects.bulk_create(
            [
                Visit(
                    address=a, result=v[0], absent_detail=v[1], created_at=v[2], election=election,
                    telegram_user_id=v[3], user_id=members.get(v[3]),
                )
                for a, v in new_visits
            ],
            batch_size=1000,
        )
        for pk, telegram_id in authors.items():
            Visit.objects.filter(pk=pk).update(telegram_user_id=telegram_id, user_id=members.get(telegram_id))
        stats["auteurs_completes"] += len(authors)
        stats["visites"] += len(new_visits)
        for _, v in new_visits:
            stats[f"resultat:{v[0]}"] += 1
        return stats

    # ----------------------------------------------------------------------------------------------- report

    def report(self, path, election, lines, totals, dry_run):
        labels = {
            VisitResult.COMMITMENT_TO_VOTE: "promesses de vote",
            VisitResult.GOOD_CONVERSATION: "bonnes conversations",
            VisitResult.NOT_INTERESTED: "peu intéressé·es",
            VisitResult.DO_NOT_CONTACT: "ne plus déranger",
            VisitResult.ADDRESS_TO_RETRY: "absent·es",
            VisitResult.ADDRESS_FAILURE: "adresses introuvables",
        }
        out = self.stdout.write
        out("")
        out(self.style.WARNING("SIMULATION (--dry-run) : rien n'a été enregistré.") if dry_run else self.style.SUCCESS("Import terminé."))
        out(f"Fichier : {path.name} · visites rattachées à : {election.name}{' (en cours)' if election.is_current else ''}")
        out("")
        for consulate, organization, new_org, s in lines:
            out(f"{consulate} → {organization.name} ({organization.code}){' — organisation créée' if new_org else ''}")
            out(
                f"   {s['lus']} lues · {s['nouvelles']} nouvelles adresses · {s['deja_en_base']} déjà sur le site · "
                f"{s['doublons_fichier']} doublons dans le fichier · {s['visites']} visites"
                + (f" · {s['invalides']} invalides" if s["invalides"] else "")
            )
        out("")
        out(self.style.SUCCESS(f"Adresses lues : {totals['lus']}"))
        out(f"Nouvelles adresses : {totals['nouvelles']}")
        out(f"Doublons (ajoutés une seule fois) : {totals['doublons_fichier']} dans le fichier, {totals['deja_en_base']} déjà sur le site")
        if totals["invalides"]:
            out(f"Lignes invalides (coordonnées manquantes) : {totals['invalides']}")
        out(f"Visites importées : {totals['visites']}")
        if totals["auteurs_completes"]:
            out(f"Visites déjà importées dont l'auteur Telegram a été complété : {totals['auteurs_completes']}")
        for key, n in sorted(((k, v) for k, v in totals.items() if k.startswith("resultat:")), key=lambda kv: -kv[1]):
            out(f"   {n} {labels.get(key.split(':', 1)[1], key)} {self.phrase(election)}")

    @staticmethod
    def phrase(election):
        from canvassing.services.elections import phrase

        return phrase(election)
