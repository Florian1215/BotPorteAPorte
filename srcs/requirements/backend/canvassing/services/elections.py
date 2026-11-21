"""Elections: one is current for the whole site.

Every visit belongs to the election current when it was made. Choosing another election starts the canvassing
over: addresses that were visited go back to "to visit" — except people who asked not to be disturbed and
addresses that do not exist, which stay out of the tours. Visits of past elections are kept (history, stats,
and "promise to vote on 12 May 2026 for the consular election" shown at the door).
"""
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from ..models import RESULT_TO_STATUS, Address, Election, Status, Visit, VisitResult

# Statuses that hold from one election to the next.
KEPT_STATUSES = (Status.DO_NOT_CONTACT, Status.FAILURE)
# Statuses that are only valid for the election during which they were given.
RESET_STATUSES = (Status.COMMITMENT_TO_VOTE, Status.GOOD_CONVERSATION, Status.NOT_INTERESTED)
# Feedbacks that keep an address out of the tours for good, whatever the election.
KEPT_RESULTS = (VisitResult.DO_NOT_CONTACT, VisitResult.ADDRESS_FAILURE)


def with_last_result(queryset):
    """Annotate `last_result`: the feedback of the most recent visit of each address (any election)."""
    last = Visit.objects.filter(address=OuterRef("pk")).order_by("-created_at", "-id").values("result")[:1]
    return queryset.annotate(last_result=Subquery(last))


def addresses_to_reset():
    """Addresses back to "to visit" with a new election: met during the previous one, and their last visit was
    not "ne plus déranger" / "adresse introuvable" (in case their status says otherwise)."""
    return with_last_result(Address.all_objects.filter(status__in=RESET_STATUSES)).exclude(last_result__in=KEPT_RESULTS)


def enforce_kept_results() -> int:
    """Addresses whose last visit, in any election, was "ne plus déranger" or "adresse introuvable" keep that
    status (out of the tours) even if their status was changed since (old imports, merges…)."""
    fixed = 0
    for result in KEPT_RESULTS:
        status = RESULT_TO_STATUS[result]
        ids = with_last_result(Address.all_objects.exclude(status=status).exclude(status=Status.PLANNED)).filter(
            last_result=result
        ).values("pk")
        fixed += Address.all_objects.filter(pk__in=ids).update(status=status, visit_planned_by=None)
    return fixed


@transaction.atomic
def set_current(election: Election) -> int:
    """Make `election` the current one. Returns the number of addresses back to "to visit"."""
    if election.is_current:
        return 0
    Election.objects.filter(is_current=True).update(is_current=False)
    election.is_current = True
    election.started_at = timezone.now()
    election.save(update_fields=["is_current", "started_at"])
    reset = Address.all_objects.filter(pk__in=addresses_to_reset().values("pk")).update(
        status=Status.TO_VISIT, visit_planned_by=None, visit_planned_at=None
    )
    enforce_kept_results()
    return reset


def phrase(election: Election | None) -> str:
    """"pour l'élection consulaire 2026" — used in messages shown at the door."""
    if election is None:
        return ""
    name = election.name.strip()
    lowered = name[0].lower() + name[1:] if name else name
    if lowered.startswith(("élection", "election")):
        return f"pour l'{lowered}"
    return f"pour « {name} »"
