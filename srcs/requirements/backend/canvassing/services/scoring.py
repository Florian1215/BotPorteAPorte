"""Score of the polling districts: where is canvassing most likely to reach our voters?

Each criterion is turned into a percentile rank among the districts of the organization (0 = lowest, 1 = highest),
so that criteria with very different units become comparable and a few extreme districts do not crush the others.
The score is the weighted mean of those ranks, from 0 to 100. A criterion with no data (no census loaded, column
missing from the import) is left out and its weight is shared among the others.
"""
from dataclasses import dataclass
from typing import Callable

from django.db import connection, transaction
from django.utils import timezone

from accounts.models import Organization

from ..models import Address, District


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    value: Callable[[District], float | None]
    # True: the higher the value, the better the district (False: the lower).
    higher_is_better: bool = True


def _ratio(num, den):
    return num / den if num is not None and den else None


def _density(d: District):
    """French voters of the organization's list per km² (set by `rescore_organization` as `n_french`)."""
    n_french = getattr(d, "n_french", None)
    return n_french / d.area_km2 if n_french is not None and d.area_km2 else None


# LFI vote by age (share of each age group voting LFI): the "age" criterion is the mean of these rates over the
# French voters of a district, i.e. the LFI vote to expect from its age structure alone.
# (lowest age included, highest included or None, rate)
LFI_VOTE_BY_AGE = [
    (18, 24, 0.41),
    (25, 34, 0.30),
    (35, 49, 0.36),
    (50, 59, 0.28),
    (60, 69, 0.24),
    (70, None, 0.19),
]


def _age_rate_sql() -> str:
    """SQL CASE: LFI vote rate of the age group of `age` (under 18 this year: with the youngest)."""
    cases = " ".join(f"WHEN age <= {high} THEN {rate}" for _, high, rate in LFI_VOTE_BY_AGE if high is not None)
    return f"CASE {cases} ELSE {LFI_VOTE_BY_AGE[-1][2]} END"


@dataclass(frozen=True)
class FrenchStats:
    """The French voters of the organization's list living in a district."""

    count: int
    # Shares among those whose birth year is known (None: no birth year at all).
    share_18_29: float | None
    share_65_plus: float | None
    # Mean LFI vote rate of their age groups (`LFI_VOTE_BY_AGE`).
    age_lfi_vote: float | None = None


def french_stats(organization_id: int, district_ids: list[int] | None = None) -> dict[int, FrenchStats]:
    """district id → French voters on the organization's list living there (active addresses), with their ages.
    The age is the one reached this year (birth year only)."""
    only = "AND d.id = ANY(%(districts)s)" if district_ids is not None else ""
    year = timezone.now().year
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT d.id,
                   COUNT(a.id),
                   COUNT(a.birth_year),
                   COUNT(a.id) FILTER (WHERE %(year)s - a.birth_year BETWEEN 18 AND 29),
                   COUNT(a.id) FILTER (WHERE %(year)s - a.birth_year >= 65),
                   AVG({_age_rate_sql()}) FILTER (WHERE a.birth_year IS NOT NULL)
            FROM {District._meta.db_table} d
            JOIN {Organization._meta.db_table} o ON o.id = d.organization_id
            LEFT JOIN {Address._meta.db_table} a
              ON a.voter_list_id = o.voter_list_id AND a.disabled_at IS NULL AND ST_Contains(d.geometry, a.location)
            CROSS JOIN LATERAL (SELECT %(year)s - a.birth_year AS age) ages
            WHERE d.organization_id = %(organization)s {only}
            GROUP BY d.id
            """,
            {
                "organization": organization_id,
                "districts": list(district_ids) if district_ids is not None else None,
                "year": year,
            },
        )
        return {
            pk: FrenchStats(
                count, young / known if known else None, old / known if known else None,
                float(rate) if rate is not None else None,
            )
            for pk, count, known, young, old, rate in cursor.fetchall()
        }


def criteria_for(organization=None) -> list[Criterion]:
    """The criteria of an organization's score: its reference party and its social indicator."""
    party = (getattr(organization, "reference_party", "") or "parti de référence").strip()
    social = (getattr(organization, "social_label", "") or "Indicateur social").strip()
    poorer_is_higher = getattr(organization, "social_higher_is_poorer", True)
    return [
        Criterion("party", f"Vote {party}", lambda d: _ratio(d.reference_votes, d.valid)),
        Criterion("abstention", "Abstention", lambda d: 1 - d.voters / d.eligible if d.voters is not None and d.eligible else None),
        # Among the French voters of the list (set by `rescore_organization` as `age_lfi_vote`), not the census.
        Criterion("age", "Âge (vote LFI attendu)", lambda d: getattr(d, "age_lfi_vote", None)),
        Criterion("density", "Densité", _density),
        # The poorer the better: a median income counts the other way round.
        Criterion("social", social, lambda d: d.social_value, higher_is_better=poorer_is_higher),
    ]


DEFAULT_WEIGHTS = {"party": 50, "abstention": 15, "age": 15, "density": 10, "social": 10}


def weights_of(organization) -> dict[str, int]:
    stored = organization.score_weights or {}
    return {key: int(stored.get(key, default)) for key, default in DEFAULT_WEIGHTS.items()}


def clean_weights(data: dict) -> dict[str, int]:
    weights = {}
    for key in DEFAULT_WEIGHTS:
        try:
            weights[key] = max(0, min(100, int(data.get(key, 0))))
        except (TypeError, ValueError):
            weights[key] = 0
    if not any(weights.values()):
        raise ValueError("Au moins un critère doit compter dans le score.")
    return weights


def percentile_ranks(values: dict[int, float]) -> dict[int, float]:
    """id → rank in [0, 1] (ties share the mean rank)."""
    if not values:
        return {}
    if len(values) == 1:
        return {k: 0.5 for k in values}
    ordered = sorted(values.items(), key=lambda kv: kv[1])
    ranks: dict[int, float] = {}
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        rank = ((i + j) / 2) / (len(ordered) - 1)
        for k in range(i, j + 1):
            ranks[ordered[k][0]] = rank
        i = j + 1
    return ranks


def compute_scores(districts: list[District], weights: dict[str, int], criteria: list[Criterion] | None = None) -> None:
    """Set `score` and `score_parts` on the districts (not saved)."""
    criteria = criteria or criteria_for()
    ranks: dict[str, dict[int, float]] = {}
    raw: dict[str, dict[int, float]] = {}
    for criterion in criteria:
        values = {d.id: v for d in districts if (v := criterion.value(d)) is not None}
        raw[criterion.key] = values
        r = percentile_ranks(values)
        ranks[criterion.key] = r if criterion.higher_is_better else {k: 1 - v for k, v in r.items()}

    for d in districts:
        parts = {}
        total_weight = 0
        total = 0.0
        for criterion in criteria:
            weight = weights.get(criterion.key, 0)
            rank = ranks[criterion.key].get(d.id)
            parts[criterion.key] = {
                "value": raw[criterion.key].get(d.id),
                "rank": rank,
                "weight": weight,
            }
            if rank is not None and weight > 0:
                total_weight += weight
                total += weight * rank
        d.score = round(100 * total / total_weight, 1) if total_weight else 0
        d.score_parts = parts


def reference_votes(parties: dict, columns: list[str]) -> float | None:
    """Votes of the reference party: the sum of its columns (several for joint lists); None if none is there."""
    found = [parties[c] for c in columns if c in parties and parties[c] is not None]
    return sum(found) if found else None


@transaction.atomic
def rescore_organization(organization) -> int:
    districts = list(District.objects.filter(organization=organization))
    columns = organization.reference_party_columns or []
    if columns:  # the reference party can be changed after the import: its votes come from the parties
        for d in districts:
            d.reference_votes = reference_votes(d.parties or {}, columns)
    stats = french_stats(organization.id)
    for d in districts:
        f = stats.get(d.id)
        d.n_french = f.count if f else 0
        d.age_lfi_vote = f.age_lfi_vote if f else None
    compute_scores(districts, weights_of(organization), criteria_for(organization))
    District.objects.bulk_update(districts, ["reference_votes", "score", "score_parts"], batch_size=500)
    return len(districts)
