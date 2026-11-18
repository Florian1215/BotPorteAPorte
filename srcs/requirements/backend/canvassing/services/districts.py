"""Import of the electoral map (polling districts + election results) of an organization.

Two ways in:
- a city pack (`packs.py`, one click): the official files of the city are downloaded by the server;
- the AI import (`ai_import.py`): an agent finds and normalizes the files of any other city.

Either way the districts of the organization are replaced, then enriched with the census grid
(`CensusCell`, loaded once for the whole site by `manage.py load_zensus`) and scored.
"""
import io
import json
import logging
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd
import requests
from django.contrib.gis.gdal import CoordTransform, SpatialReference
from django.contrib.gis.geos import GEOSException, GEOSGeometry, MultiPolygon, Polygon
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from accounts.models import Organization

from ..models import District, DistrictImport
from . import scoring

log = logging.getLogger(__name__)

HTTP_TIMEOUT = 180
USER_AGENT = "canvassing-app (porte-a-porte)"


class DistrictImportError(Exception):
    pass


@dataclass
class DistrictRow:
    code: str
    name: str
    geometry: MultiPolygon
    eligible: float | None = None
    voters: float | None = None
    valid: float | None = None
    reference_votes: float | None = None
    parties: dict = field(default_factory=dict)
    social_value: float | None = None  # when the indicator comes per district (else from `SocialArea`s)


@dataclass
class ImportSettings:
    """What an import tells about the organization: its reference party and social indicator."""

    reference_party: str = ""
    reference_party_columns: list[str] = field(default_factory=list)
    social_label: str | None = None  # None: unchanged
    social_higher_is_poorer: bool = True


# --------------------------------------------------------------------------- helpers


def normalize_id(value) -> str:
    """Identifiers as written in different files: "01127", 1127, "1127.0" are the same district."""
    s = str(value).strip()
    if re.fullmatch(r"-?\d+\.0+", s):
        s = s.split(".")[0]
    if s.isdigit():
        return s.lstrip("0") or "0"
    return s.upper()


def to_number(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None if pd.isna(value) else float(value)
    s = str(value).strip().replace(" ", "").replace(" ", "")
    if not s or s in {"-", "–", "—", ".", "x", "/"}:
        return None
    if "," in s and "." in s:  # 1.234,5
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def as_multipolygon(geometry: GEOSGeometry) -> MultiPolygon | None:
    if not geometry.valid:
        geometry = geometry.make_valid()
    if isinstance(geometry, Polygon):
        return MultiPolygon(geometry, srid=geometry.srid)
    if isinstance(geometry, MultiPolygon):
        return geometry
    polygons = [g for g in getattr(geometry, "__iter__", lambda: iter(()))() if isinstance(g, (Polygon, MultiPolygon))]
    flat = []
    for g in polygons:
        flat.extend([g] if isinstance(g, Polygon) else list(g))
    return MultiPolygon(*flat, srid=geometry.srid) if flat else None


def _crs_of(collection: dict) -> int:
    name = ((collection.get("crs") or {}).get("properties") or {}).get("name", "")
    match = re.search(r"(\d{4,6})\s*$", name)
    return int(match.group(1)) if match and "CRS84" not in name else 4326


def read_geojson(data: bytes) -> list[dict]:
    """Features of a GeoJSON FeatureCollection, geometries in EPSG:4326 (`_geometry`)."""
    try:
        collection = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise DistrictImportError("Le fichier des bureaux n'est pas un GeoJSON valide.") from None
    if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection":
        raise DistrictImportError("Le fichier des bureaux doit être un GeoJSON de type « FeatureCollection ».")
    srid = _crs_of(collection)
    transform = CoordTransform(SpatialReference(srid), SpatialReference(4326)) if srid != 4326 else None
    features = []
    for feature in collection.get("features") or []:
        if not feature.get("geometry"):
            continue
        try:
            geometry = GEOSGeometry(json.dumps(feature["geometry"]), srid=srid)
            if transform:
                geometry.transform(transform)
            geometry = as_multipolygon(geometry)
        except (GEOSException, ValueError, TypeError):
            continue
        if geometry is None or geometry.empty:
            continue
        features.append({**(feature.get("properties") or {}), "_geometry": geometry})
    if not features:
        raise DistrictImportError("Aucun polygone trouvé dans le fichier des bureaux.")
    return features


def merge_by(features: list[dict], key) -> dict[str, dict]:
    """Features sharing the same identifier (a district drawn in several pieces) → one feature, outlines merged."""
    merged: dict[str, dict] = {}
    for feature in features:
        k = key(feature)
        if k in merged:
            union = merged[k]["_geometry"].union(feature["_geometry"])
            merged[k]["_geometry"] = as_multipolygon(union) or merged[k]["_geometry"]
        else:
            merged[k] = dict(feature)
    return merged


def read_table(data: bytes, filename: str, sheet: str | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Results table (CSV or Excel) → (dataframe of strings, sheet names)."""
    name = filename.lower()
    try:
        if name.endswith((".xlsx", ".xlsm", ".xls")):
            book = pd.ExcelFile(io.BytesIO(data))
            sheets = book.sheet_names
            df = book.parse(sheet if sheet in sheets else sheets[0], dtype=str)
            return df, sheets
        text = data.decode("utf-8-sig", errors="replace")
        df = pd.read_csv(io.StringIO(text), sep=None, engine="python", dtype=str)
        return df, []
    except DistrictImportError:
        raise
    except Exception as exc:  # pandas raises many kinds of errors on unreadable files
        raise DistrictImportError(f"Impossible de lire le fichier des résultats : {exc}") from None


# --------------------------------------------------------------------------- saving


@transaction.atomic
def save_districts(organization, rows: list[DistrictRow], election: str, settings: ImportSettings | None = None) -> dict:
    """Replace the districts of the organization, then add census figures and scores."""
    if settings is not None:
        fields = []
        if settings.reference_party_columns:
            organization.reference_party = (settings.reference_party or settings.reference_party_columns[0])[:128]
            organization.reference_party_columns = settings.reference_party_columns
            fields += ["reference_party", "reference_party_columns"]
        if settings.social_label is not None:
            organization.social_label = settings.social_label[:128]
            organization.social_higher_is_poorer = settings.social_higher_is_poorer
            fields += ["social_label", "social_higher_is_poorer"]
        if fields:
            organization.save(update_fields=fields)
    District.objects.filter(organization=organization).delete()
    District.objects.bulk_create(
        [
            District(
                organization=organization,
                code=r.code,
                name=r.name[:255],
                geometry=r.geometry,
                election=election,
                eligible=r.eligible,
                voters=r.voters,
                valid=r.valid,
                reference_votes=r.reference_votes,
                parties=r.parties,
                social_value=r.social_value,
            )
            for r in rows
        ],
        batch_size=500,
    )
    table = District._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {table} SET
                geometry_simple = ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SimplifyPreserveTopology(geometry, 0.00003)), 3)),
                label_point = ST_PointOnSurface(geometry),
                area_km2 = ST_Area(geometry::geography) / 1e6
            WHERE organization_id = %s
            """,
            [organization.id],
        )
    n_with_census = add_census(organization)
    n_with_social = sum(r.social_value is not None for r in rows)
    if not n_with_social:
        n_with_social = add_social(organization)
    scoring.rescore_organization(organization)
    return {"n_districts": len(rows), "n_with_census": n_with_census, "n_with_social": n_with_social}


def add_census(organization) -> int:
    """Census 2022 figures of each district, from the 100 m cells whose centre lies inside it."""
    table = District._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {table} AS d SET
                population = a.population,
                share_18_29 = a.age_18_29::float / NULLIF(a.age_known, 0),
                share_65_plus = a.age_65_plus::float / NULLIF(a.age_known, 0),
                share_foreign = a.foreign_weighted / NULLIF(a.foreign_population, 0),
                rent_m2 = a.rent_weighted / NULLIF(a.rent_dwellings, 0)
            FROM (
                SELECT d.id,
                       SUM(c.population) AS population,
                       SUM(c.age_known) AS age_known,
                       SUM(c.age_18_29) AS age_18_29,
                       SUM(c.age_65_plus) AS age_65_plus,
                       SUM(c.share_foreign * c.population) FILTER (WHERE c.share_foreign IS NOT NULL) AS foreign_weighted,
                       SUM(c.population) FILTER (WHERE c.share_foreign IS NOT NULL) AS foreign_population,
                       SUM(c.rent_m2 * c.dwellings) FILTER (WHERE c.rent_m2 IS NOT NULL AND c.dwellings > 0) AS rent_weighted,
                       SUM(c.dwellings) FILTER (WHERE c.rent_m2 IS NOT NULL AND c.dwellings > 0) AS rent_dwellings
                FROM {table} d
                JOIN canvassing_censuscell c ON ST_Contains(d.geometry, c.point)
                WHERE d.organization_id = %s
                GROUP BY d.id
            ) AS a
            WHERE d.id = a.id
            """,
            [organization.id],
        )
        n = cursor.rowcount
        if n:
            # Census loaded for this area: districts without any populated cell (parks, industry) have nobody.
            cursor.execute(f"UPDATE {table} SET population = 0 WHERE organization_id = %s AND population IS NULL", [organization.id])
    return n


def add_social(organization) -> int:
    """Social indicator of each district, from the `SocialArea`s it overlaps: the organization's own ones (found
    by the AI import) or else the shared ones (e.g. Berlin MSS, share of low-income residents).

    Population-weighted: each census cell of the district takes the value of the area it lies in, so that a
    district straddling a poor estate and a park is not diluted by the park. Districts without census cells
    fall back on the overlapping area of each social area.
    """
    from ..models import CensusCell, SocialArea

    table = District._meta.db_table
    social = SocialArea._meta.db_table
    own = SocialArea.objects.filter(organization=organization).exists()
    params = {"organization": organization.id}
    # Only the organization's areas if it has some (another indicator: never mixed with the shared ones).
    areas = "s.organization_id = %(organization)s" if own else "s.organization_id IS NULL"
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {table} SET social_value = NULL WHERE organization_id = %(organization)s", params)
        cursor.execute(
            f"""
            UPDATE {table} AS d SET social_value = a.value
            FROM (
                SELECT d.id, SUM(c.population * s.low_income) / NULLIF(SUM(c.population), 0) AS value
                FROM {table} d
                JOIN {CensusCell._meta.db_table} c ON ST_Contains(d.geometry, c.point)
                JOIN {social} s ON s.low_income IS NOT NULL AND {areas} AND ST_Contains(s.geometry, c.point)
                WHERE d.organization_id = %(organization)s
                GROUP BY d.id
            ) AS a
            WHERE d.id = a.id
            """,
            params,
        )
        n = cursor.rowcount
        cursor.execute(
            f"""
            UPDATE {table} AS d SET social_value = a.value
            FROM (
                SELECT d.id,
                       SUM(ST_Area(ST_Intersection(d.geometry, s.geometry)) * s.low_income)
                         / NULLIF(SUM(ST_Area(ST_Intersection(d.geometry, s.geometry))), 0) AS value
                FROM {table} d
                JOIN {social} s ON s.low_income IS NOT NULL AND {areas} AND ST_Intersects(d.geometry, s.geometry)
                WHERE d.organization_id = %(organization)s AND d.social_value IS NULL
                GROUP BY d.id
            ) AS a
            WHERE d.id = a.id
            """,
            params,
        )
        return n + cursor.rowcount


# --------------------------------------------------------------------------- progress


def progress(organization_id: int, district_ids: list[int] | None = None, election=None) -> dict[int, dict]:
    """Per district, the organization's addresses (= French voters on the list) inside, for one election
    (default: the current one). Only the visits of that election count: a new election starts at 0 %.

    - `total`: the addresses concerned by this election. Not counted: people who asked not to be disturbed and
      addresses not found during an earlier election (they stay out of the tours), unless visited in this one;
    - `done` / `done_pct`: people met during this election (or address settled: not found, do not contact);
    - `remaining` = total - done, split into `leafleted` (came during this election, nobody answered, a leaflet was
      left) and `not_leafleted` (nobody came yet, or the mailbox was inaccessible);
    - `to_visit`: addresses free to be put in a new tour right now (current state, whatever the election).
    """
    from ..models import AbsentDetail, Address, Election, Status, Visit, VisitResult

    if election is None:
        election = Election.current()
    params: dict = {
        "organization": organization_id,
        "to_visit": Status.TO_VISIT,
        "retry": VisitResult.ADDRESS_TO_RETRY,
        "inaccessible": AbsentDetail.MAILBOX_INACCESSIBLE,
        "settled": [VisitResult.DO_NOT_CONTACT, VisitResult.ADDRESS_FAILURE],
        "election": election.id if election else None,
        "earlier": list(Election.objects.filter(created_at__lt=election.created_at).values_list("id", flat=True))
        if election
        else [],
        "districts": list(district_ids) if district_ids is not None else None,
    }
    visits = Visit._meta.db_table
    # No election at all on the site: every visit counts.
    in_election = "AND v.election_id = %(election)s" if election else ""
    only = "AND d.id = ANY(%(districts)s)" if district_ids is not None else ""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT d.id,
                   COUNT(a.id) FILTER (WHERE NOT f.carried),
                   COUNT(a.id) FILTER (WHERE a.status = %(to_visit)s),
                   COUNT(a.id) FILTER (WHERE f.done),
                   COUNT(a.id) FILTER (WHERE NOT f.done AND NOT f.carried AND f.leafleted)
            FROM {District._meta.db_table} d
            JOIN {Organization._meta.db_table} o ON o.id = d.organization_id
            JOIN {Address._meta.db_table} a
              ON a.voter_list_id = o.voter_list_id AND a.disabled_at IS NULL AND ST_Contains(d.geometry, a.location)
            CROSS JOIN LATERAL (
                SELECT
                    EXISTS (SELECT 1 FROM {visits} v WHERE v.address_id = a.id AND v.result <> %(retry)s {in_election}) AS done,
                    EXISTS (
                        SELECT 1 FROM {visits} v
                        WHERE v.address_id = a.id AND v.result = %(retry)s AND v.absent_detail <> %(inaccessible)s {in_election}
                    ) AS leafleted,
                    (
                        EXISTS (
                            SELECT 1 FROM {visits} v
                            WHERE v.address_id = a.id AND v.result = ANY(%(settled)s) AND v.election_id = ANY(%(earlier)s)
                        )
                        AND NOT EXISTS (SELECT 1 FROM {visits} v WHERE v.address_id = a.id {in_election})
                    ) AS carried
            ) f
            WHERE d.organization_id = %(organization)s {only}
            GROUP BY d.id
            """,
            params,
        )
        result = {}
        for pk, total, to_visit, done, n_leafleted in cursor.fetchall():
            remaining = total - done
            result[pk] = {
                "total": total,
                "to_visit": to_visit,
                "remaining": remaining,
                "not_leafleted": remaining - n_leafleted,
                "leafleted": n_leafleted,
                "done": done,
                "done_pct": round(100 * done / total, 1) if total else 0,
            }
        return result


EMPTY_PROGRESS = {"total": 0, "to_visit": 0, "remaining": 0, "not_leafleted": 0, "leafleted": 0, "done": 0, "done_pct": 0}

# Age groups of the pyramid: (label, min age, max age included).
AGE_GROUPS = [
    ("18–24", 18, 24),
    ("25–34", 25, 34),
    ("35–44", 35, 44),
    ("45–54", 45, 54),
    ("55–64", 55, 64),
    ("65–74", 65, 74),
    ("75+", 75, None),
]


def age_pyramid(district: District) -> dict:
    """Age of the organization's addresses (French voters) in the district, from their year of birth.

    The age is the one reached this year (the list keeps only the year of birth).
    """
    from django.db.models import Count

    from ..models import Address

    year = timezone.localdate().year
    counts = dict(
        Address.objects.filter(voter_list_id=district.organization.voter_list_id, location__within=district.geometry)
        .values_list("birth_year")
        .annotate(n=Count("id"))
        .order_by()
    )
    unknown = counts.pop(None, 0)
    groups = []
    for label, low, high in AGE_GROUPS:
        n = sum(c for birth, c in counts.items() if year - birth >= low and (high is None or year - birth <= high))
        groups.append({"label": label, "count": n})
    # Under 18 this year (born late in the year, or a typo in the list): with the youngest.
    groups[0]["count"] += sum(c for birth, c in counts.items() if year - birth < AGE_GROUPS[0][1])
    return {"groups": groups, "unknown": unknown}


# --------------------------------------------------------------------------- normalized files (AI import)

NORMALIZED_COUNTS = ("eligible", "voters", "valid")


def rows_from_normalized(geometry_data: bytes, results_data: bytes, social_data: bytes | None = None) -> tuple[list[DistrictRow], dict]:
    """The files the AI agent writes (see `ai_import.OUTPUT_CONTRACT`): `districts.geojson` (properties `id`,
    `name`), `results.csv` (`id`, `eligible`, `voters`, `valid`, then one column of votes per party) and
    optionally `social.csv` (`id`, `value`)."""
    features = read_geojson(geometry_data)
    if "id" not in features[0]:
        raise DistrictImportError("districts.geojson : chaque zone doit avoir une propriété « id ».")
    df, _ = read_table(results_data, "results.csv")
    df.columns = [str(c).strip() for c in df.columns]
    if "id" not in df.columns or "valid" not in df.columns:
        raise DistrictImportError("results.csv : colonnes « id » et « valid » obligatoires.")
    party_columns = [c for c in df.columns if c not in ("id", "name", *NORMALIZED_COUNTS)]
    if not party_columns:
        raise DistrictImportError("results.csv : aucune colonne de parti (une colonne de voix par parti).")

    results: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    for record in df.to_dict(orient="records"):
        key = normalize_id(record.get("id"))
        if not key or key == "NAN":
            continue
        for col in (*NORMALIZED_COUNTS, *party_columns):
            if col in df.columns and (v := to_number(record.get(col))) is not None:
                results[key][col] += v

    social: dict[str, float] = {}
    if social_data:
        sdf, _ = read_table(social_data, "social.csv")
        sdf.columns = [str(c).strip() for c in sdf.columns]
        if "id" not in sdf.columns or "value" not in sdf.columns:
            raise DistrictImportError("social.csv : colonnes « id » et « value » obligatoires.")
        for record in sdf.to_dict(orient="records"):
            if (v := to_number(record.get("value"))) is not None:
                social[normalize_id(record.get("id"))] = v

    rows, unmatched = [], []
    for key, feature in merge_by(features, lambda f: normalize_id(f.get("id"))).items():
        result = results.get(key)
        if result is None:
            unmatched.append(str(feature.get("id")))
            result = {}
        name = feature.get("name")
        rows.append(
            DistrictRow(
                code=str(feature.get("id"))[:32],
                name=str(name) if name not in (None, "") else f"Zone {feature.get('id')}",
                geometry=feature["_geometry"],
                eligible=result.get("eligible"),
                voters=result.get("voters"),
                valid=result.get("valid"),
                parties={c: result[c] for c in party_columns if c in result},
                social_value=social.get(key),
            )
        )
    report = {
        "n_without_results": len(unmatched),
        "examples_without_results": unmatched[:10],
        "n_results_without_district": len(set(results) - {normalize_id(f.get("id")) for f in features}),
        "party_columns": party_columns,
    }
    return rows, report


def social_areas_from_geojson(organization, data: bytes, source: str) -> int:
    """`social.geojson` of the AI import (polygons with a numeric `value`) → the organization's `SocialArea`s."""
    from ..models import SocialArea

    features = read_geojson(data)
    areas = []
    for i, feature in enumerate(features):
        value = to_number(feature.get("value"))
        if value is None:
            continue
        areas.append(SocialArea(
            organization=organization, source=source[:32], code=str(feature.get("id") or i)[:32],
            name=str(feature.get("name") or "")[:255], geometry=feature["_geometry"], low_income=value,
        ))
    if not areas:
        raise DistrictImportError("social.geojson : aucune zone avec une « value » numérique.")
    SocialArea.objects.filter(organization=organization).delete()
    SocialArea.objects.bulk_create(areas, batch_size=500, ignore_conflicts=True)
    return len(areas)


# --------------------------------------------------------------------------- Berlin (see `packs.py`)

BERLIN_WFS = (
    "https://gdi.berlin.de/services/wfs/wahlgebiete_agh2026?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
    "&TYPENAMES=wahlgebiete_agh2026:agh2026_uwb&OUTPUTFORMAT=application/json&SRSNAME=EPSG:4326"
)
BERLIN_RESULTS = "https://www.wahlen-berlin.de/wahlen/BE2026/Afspraes/agh/DL/DL_BE_AGHBVV2026.xlsx"
BERLIN_ELECTION = "Abgeordnetenhaus de Berlin, 20/09/2026 (2e voix)"
BERLIN_FIRST_PARTY_COLUMN = "CDU"


def rows_from_berlin(geometry_data: bytes, results_data: bytes) -> tuple[list[DistrictRow], dict]:
    """Berlin: ballot-box districts (Urnenwahlbezirke) + postal votes, counted per postal district
    (Briefwahlbezirk, covering 1–3 ballot-box districts) and shared among them in proportion to the
    voters who asked for a postal vote (Wahlberechtigte A2)."""
    features = read_geojson(geometry_data)
    df = pd.read_excel(io.BytesIO(results_data), sheet_name="AGH_W2")
    df.columns = [str(c).replace("\n", "").replace("-", "").strip() for c in df.columns]
    parties = list(df.columns[list(df.columns).index(BERLIN_FIRST_PARTY_COLUMN):])
    counts = ["Wählende", "Gültige Stimmen", *parties]

    def num(v):
        return to_number(v) or 0.0

    ballot = {}  # "01127" → row
    postal = {}  # ("01", "1A") → row
    for record in df.to_dict(orient="records"):
        bez = f"{int(num(record['Bezirksnummer'])):02d}"
        if record["Wahlbezirksart"] == "W":
            ballot[f"{bez}{int(num(record['Wahlbezirk'])):03d}"] = record
        else:
            postal[(bez, str(record["Briefwahlbezirk"]).strip())] = record

    by_postal = defaultdict(list)
    for code, record in ballot.items():
        by_postal[(code[:2], str(record["Briefwahlbezirk"]).strip())].append(code)

    totals = {code: {c: num(record[c]) for c in counts} for code, record in ballot.items()}
    for key, record in postal.items():
        members = by_postal.get(key, [])
        if not members:
            continue
        weights = [num(ballot[m]["Wahlberechtigte A2"]) for m in members]
        if not sum(weights):
            weights = [num(ballot[m]["Wahlberechtigte insgesamt"]) or 1 for m in members]
        total_weight = sum(weights)
        for member, weight in zip(members, weights):
            for c in counts:
                totals[member][c] += num(record[c]) * weight / total_weight

    rows, unmatched = [], []
    for code, feature in merge_by(features, lambda f: str(f.get("uwb"))).items():
        record = ballot.get(code)
        if record is None:
            unmatched.append(code)
            continue
        t = totals[code]
        rows.append(
            DistrictRow(
                code=code,
                name=f"{record['Bezirksname']} – bureau {code[2:]}",
                geometry=feature["_geometry"],
                eligible=num(record["Wahlberechtigte insgesamt"]),
                voters=round(t["Wählende"], 1),
                valid=round(t["Gültige Stimmen"], 1),
                reference_votes=round(t["Die Linke"], 1),
                parties={p: round(t[p], 1) for p in parties if t[p]},
            )
        )
    report = {"n_without_results": len(unmatched), "examples_without_results": unmatched[:10]}
    return rows, report


BERLIN_SETTINGS = ImportSettings(
    reference_party="Die Linke", reference_party_columns=["Die Linke"],
    social_label="Part de bas revenus (MSS 2023)", social_higher_is_poorer=True,
)


# --------------------------------------------------------------------------- background run



NO_SOCIAL_LABEL = "Indicateur social (aucune donnée)"


def start_import(job: DistrictImport) -> None:
    job.status = DistrictImport.ImportStatus.RUNNING
    job.message = ""
    job.save(update_fields=["status", "message"])
    thread = threading.Thread(target=_run, args=(job.id,), daemon=True)
    thread.start()


def _run(job_id: int) -> None:
    from . import packs

    close_old_connections()
    job = DistrictImport.objects.select_related("organization").get(pk=job_id)
    try:
        result = packs.run(job.source)
        report = result.report
        report.update(save_districts(job.organization, result.rows, result.election, result.settings))
        organization = job.organization
        if result.social_from_rent:
            report["n_with_social"] = packs.social_from_rent(organization)
            scoring.rescore_organization(organization)
        elif not report.get("n_with_social"):
            organization.social_label = NO_SOCIAL_LABEL  # the score does without it
            organization.save(update_fields=["social_label"])
            scoring.rescore_organization(organization)
        job.status = DistrictImport.ImportStatus.DONE
        job.report = report
    except DistrictImportError as exc:
        job.status, job.message = DistrictImport.ImportStatus.FAILED, str(exc)
    except requests.RequestException as exc:
        job.status, job.message = DistrictImport.ImportStatus.FAILED, f"Téléchargement impossible : {exc}"
    except Exception as exc:  # noqa: BLE001 - reported to the user, details in the logs
        log.exception("District import %s failed", job_id)
        job.status, job.message = DistrictImport.ImportStatus.FAILED, f"Erreur inattendue : {exc}"
    job.finished_at = timezone.now()
    job.save()
    close_old_connections()
