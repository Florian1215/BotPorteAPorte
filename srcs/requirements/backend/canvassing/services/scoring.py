"""Score of the polling districts: where is canvassing most likely to reach our voters?

Each criterion is turned into a percentile rank among the districts of the organization (0 = lowest, 1 = highest),
so that criteria with very different units become comparable and a few extreme districts do not crush the others.
The score is the weighted mean of those ranks, from 0 to 100. A criterion with no data (no census loaded, column
missing from the import) is left out and its weight is shared among the others.
"""
from dataclasses import dataclass
from typing import Callable

from django.db import transaction

from ..models import District


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    value: Callable[[District], float | None]
    # True: the higher the value, the better the district (False: the lower, e.g. rent).
    higher_is_better: bool = True


def _ratio(num, den):
    return num / den if num is not None and den else None


def _density(d: District):
    if not d.area_km2:
        return None
    people = d.population if d.population is not None else d.eligible
    return people / d.area_km2 if people is not None else None


CRITERIA = [
    Criterion("linke", "Vote Die Linke", lambda d: _ratio(d.linke, d.valid)),
    Criterion("abstention", "Abstention", lambda d: 1 - d.voters / d.eligible if d.voters is not None and d.eligible else None),
    Criterion("young", "18–29 ans", lambda d: d.share_18_29),
    Criterion("density", "Densité", _density),
    Criterion("low_rent", "Loyers bas", lambda d: d.rent_m2, higher_is_better=False),
]
CRITERIA_BY_KEY = {c.key: c for c in CRITERIA}

DEFAULT_WEIGHTS = {"linke": 50, "abstention": 15, "young": 15, "density": 10, "low_rent": 10}


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


def compute_scores(districts: list[District], weights: dict[str, int]) -> None:
    """Set `score` and `score_parts` on the districts (not saved)."""
    ranks: dict[str, dict[int, float]] = {}
    raw: dict[str, dict[int, float]] = {}
    for criterion in CRITERIA:
        values = {d.id: v for d in districts if (v := criterion.value(d)) is not None}
        raw[criterion.key] = values
        r = percentile_ranks(values)
        ranks[criterion.key] = r if criterion.higher_is_better else {k: 1 - v for k, v in r.items()}

    for d in districts:
        parts = {}
        total_weight = 0
        total = 0.0
        for criterion in CRITERIA:
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


@transaction.atomic
def rescore_organization(organization) -> int:
    districts = list(District.objects.filter(organization=organization))
    compute_scores(districts, weights_of(organization))
    District.objects.bulk_update(districts, ["score", "score_parts"], batch_size=500)
    return len(districts)
