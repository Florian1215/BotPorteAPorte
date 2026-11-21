"""Merge the addresses imported from the Telegram bot into the same person's row of the voter list (LEC).

    manage.py dedupe_addresses            # simulation: shows what would be merged, changes nothing
    manage.py dedupe_addresses --apply    # does it
    manage.py dedupe_addresses --list "LEC Berlin" --apply

Why: the bot only kept one first name ("Marie"), the LEC has them all ("Marie Claire Anne"), the birth year…
so `import_bot_db` did not recognize people already imported from the LEC, and created a second row for them.

For each row coming from the bot (no LEC data: no birth year, no original address, no "lec:" key), the command
looks in the same list for a LEC row of the same person: same name, its first name(s) among the LEC's first names,
same postcode (the street decides between homonyms). When exactly one is found:
- the bot row's visits and tour stops are moved to the LEC row (history, statistics and rankings are kept);
- the LEC row takes the bot row's status if it was still "to visit" (promise, do not contact…);
- the bot row is deleted. The LEC row (all names, birth year…) is the one kept.
Bot rows with no LEC match, or several possible matches, are left untouched (listed in the report).
"""
import re
import unicodedata
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import VoterList
from canvassing.models import Address, Status, TourStop, Visit, semi_anonymize_name
from canvassing.services.address_import import normalize_street


def norm(text: str) -> str:
    """Lowercase, no accents, words only: "Müller-Lüdenscheidt " → "muller ludenscheidt"."""
    text = unicodedata.normalize("NFKD", (text or "").replace("ß", "ss")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z*]+", " ", text.lower()).split())


def is_lec_row(a: Address) -> bool:
    """Imported from the LEC file (the bot never had these fields)."""
    return bool(a.birth_year or a.source_address or a.source_key.startswith("lec:"))


def same_name(bot: str, lec: str) -> bool:
    if bot == lec:
        return True
    # Old lists stored names semi-anonymized ("mar***"): compare what is left.
    return ("*" in bot or "*" in lec) and semi_anonymize_name(bot) == semi_anonymize_name(lec)


def zip_of(a: Address) -> str:
    return re.sub(r"\s+", "", a.zip_code or "").lower()


def street_of(a: Address) -> str:
    return normalize_street(a.address or "")


class Command(BaseCommand):
    help = "Merge the addresses imported from the Telegram bot into the matching LEC row (same person)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Really merge (without it: simulation)")
        parser.add_argument("--list", help="Only this voter list (name or id)")
        parser.add_argument("--verbose-list", action="store_true", help="List every merge and every row left as is")

    def handle(self, *args, **opts):
        lists = VoterList.objects.all()
        if opts["list"]:
            key = opts["list"]
            lists = lists.filter(pk=int(key)) if key.isdigit() else lists.filter(name__iexact=key)
            if not lists.exists():
                raise CommandError(f"LEC introuvable : {key}")

        totals = Counter()
        with transaction.atomic():
            for voter_list in lists.order_by("name"):
                stats, details = self.dedupe(voter_list)
                totals.update(stats)
                if stats["bot"]:
                    self.stdout.write(
                        f"{voter_list.name} : {stats['bot']} adresses du bot · {stats['fusionnees']} fusionnées avec la LEC · "
                        f"{stats['sans_correspondance']} sans correspondance · {stats['ambigues']} ambiguës"
                    )
                if opts["verbose_list"]:
                    for line in details:
                        self.stdout.write(f"   {line}")
            if not opts["apply"]:
                transaction.set_rollback(True)

        out = self.stdout.write
        out("")
        out(self.style.SUCCESS("Nettoyage terminé.") if opts["apply"] else self.style.WARNING("SIMULATION : rien n'a été modifié (ajoute --apply)."))
        out(f"Adresses venant du bot : {totals['bot']}")
        out(f"Fusionnées avec la fiche LEC (supprimées) : {totals['fusionnees']}")
        out(f"   visites déplacées : {totals['visites']} · arrêts de tournée déplacés : {totals['arrets']}")
        out(f"   statut repris par la fiche LEC : {totals['statuts']}")
        out(f"Gardées telles quelles : {totals['sans_correspondance']} sans fiche LEC, {totals['ambigues']} ambiguës (plusieurs fiches possibles)")

    def dedupe(self, voter_list: VoterList) -> tuple[Counter, list[str]]:
        stats = Counter()
        details: list[str] = []
        rows = list(Address.all_objects.filter(voter_list=voter_list))
        lec_rows = [a for a in rows if is_lec_row(a)]
        bot_rows = [a for a in rows if not is_lec_row(a)]
        stats["bot"] = len(bot_rows)
        if not bot_rows or not lec_rows:
            stats["sans_correspondance"] = len(bot_rows)
            return stats, details

        by_zip: dict[str, list[Address]] = defaultdict(list)
        for a in lec_rows:
            by_zip[zip_of(a)].append(a)

        merges: list[tuple[Address, Address]] = []
        for bot in bot_rows:
            name, first = norm(bot.name), set(norm(bot.first_names).split())
            candidates = [
                lec
                for lec in by_zip.get(zip_of(bot), [])
                if same_name(name, norm(lec.name)) and first and first <= set(norm(lec.first_names).split())
            ]
            if len(candidates) > 1:
                # Homonyms in the same postcode: the street decides; then prefer the rows still in the list.
                candidates = [c for c in candidates if street_of(c) == street_of(bot)] or candidates
                if len(candidates) > 1:
                    active = [c for c in candidates if c.disabled_at is None]
                    candidates = active if len(active) == 1 else candidates
            label = f"{bot.first_names} {bot.name}, {bot.full_address} (#{bot.id})"
            if not candidates:
                stats["sans_correspondance"] += 1
                details.append(f"sans fiche LEC : {label}")
            elif len(candidates) > 1:
                stats["ambigues"] += 1
                details.append(f"ambiguë ({len(candidates)} fiches) : {label}")
            else:
                merges.append((bot, candidates[0]))
                details.append(f"fusion : {label} → {candidates[0].first_names} {candidates[0].name} (#{candidates[0].id})")

        for bot, lec in merges:
            self.merge(bot, lec, stats)
        return stats, details

    def merge(self, bot: Address, lec: Address, stats: Counter) -> None:
        # Visits: moved, unless the LEC row already has the same one (same result at the same time).
        known = set(Visit.objects.filter(address=lec).values_list("result", "created_at"))
        for visit in Visit.objects.filter(address=bot):
            if (visit.result, visit.created_at) in known:
                visit.delete()
            else:
                visit.address = lec
                visit.save(update_fields=["address"])
                stats["visites"] += 1
        stats["arrets"] += TourStop.objects.filter(address=bot).update(address=lec)

        # The LEC row keeps its own result; it only takes the bot's when it had none.
        if lec.status == Status.TO_VISIT and bot.status != Status.TO_VISIT:
            lec.status = bot.status
            lec.visit_planned_at = bot.visit_planned_at
            lec.visit_planned_by = bot.visit_planned_by
            lec.save(update_fields=["status", "visit_planned_at", "visit_planned_by"])
            stats["statuts"] += 1
        elif lec.visit_planned_at is None and bot.visit_planned_at is not None:
            lec.visit_planned_at = bot.visit_planned_at
            lec.save(update_fields=["visit_planned_at"])

        bot.delete()
        stats["fusionnees"] += 1
