"""Elections: one is current for the whole site.

Every visit belongs to the election current when it was made. Choosing another election starts the canvassing
over: addresses that were visited go back to "to visit" — except people who asked not to be disturbed and
addresses that do not exist, which stay out of the tours. Visits of past elections are kept (history, stats,
and "promise to vote on 12 May 2026 for the consular election" shown at the door).
"""
from django.db import transaction
from django.utils import timezone

from ..models import Address, Election, Status

# Statuses that hold from one election to the next.
KEPT_STATUSES = (Status.DO_NOT_CONTACT, Status.FAILURE)
# Statuses that are only valid for the election during which they were given.
RESET_STATUSES = (Status.COMMITMENT_TO_VOTE, Status.GOOD_CONVERSATION, Status.NOT_INTERESTED)


def addresses_to_reset():
    return Address.all_objects.filter(status__in=RESET_STATUSES)


@transaction.atomic
def set_current(election: Election) -> int:
    """Make `election` the current one. Returns the number of addresses back to "to visit"."""
    if election.is_current:
        return 0
    Election.objects.filter(is_current=True).update(is_current=False)
    election.is_current = True
    election.started_at = timezone.now()
    election.save(update_fields=["is_current", "started_at"])
    return addresses_to_reset().update(status=Status.TO_VISIT, visit_planned_by=None, visit_planned_at=None)


def phrase(election: Election | None) -> str:
    """"pour l'élection consulaire 2026" — used in messages shown at the door."""
    if election is None:
        return ""
    name = election.name.strip()
    lowered = name[0].lower() + name[1:] if name else name
    if lowered.startswith(("élection", "election")):
        return f"pour l'{lowered}"
    return f"pour « {name} »"
