"""Import of the electoral map (polling districts + election results) of an organization.

Two ways in:
- a preset (one click): the official files of a city are downloaded by the server (Berlin for now);
- a custom import: a GeoJSON of the districts + a results file (CSV / XLSX), with the columns picked by the user.

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
    linke: float | None = None
    parties: dict = field(default_factory=dict)


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


def inspect_files(geometry_data: bytes, results_data: bytes, results_filename: str, sheet: str | None = None) -> dict:
    """Columns and a preview of both files, to let the user pick the columns."""
    features = read_geojson(geometry_data)
    df, sheets = read_table(results_data, results_filename, sheet)
    df.columns = [str(c).replace("\n", " ").strip() for c in df.columns]
    properties = [k for k in features[0] if k != "_geometry"]
    return {
        "n_features": len(features),
        "geometry_properties": properties,
        "geometry_preview": [{k: _plain(f.get(k)) for k in properties} for f in features[:3]],
        "sheets": sheets,
        "sheet": sheet if sheet in sheets else (sheets[0] if sheets else None),
        "n_rows": len(df),
        "columns": list(df.columns),
        "preview": df.head(3).fillna("").to_dict(orient="records"),
    }


def _plain(value):
    return value if isinstance(value, (str, int, float, bool)) or value is None else str(value)


# --------------------------------------------------------------------------- saving


@transaction.atomic
def save_districts(organization, rows: list[DistrictRow], election: str) -> dict:
    """Replace the districts of the organization, then add census figures and scores."""
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
                linke=r.linke,
                parties=r.parties,
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
    scoring.rescore_organization(organization)
    return {"n_districts": len(rows), "n_with_census": n_with_census}


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


# --------------------------------------------------------------------------- progress


def progress(organization_id: int, district_ids: list[int] | None = None) -> dict[int, dict]:
    """Per district: addresses of the organization inside, still to visit, and doors done (visited at least once)."""
    from ..models import Address, Status, Visit

    table = District._meta.db_table
    params: list = [Status.TO_VISIT, organization_id]
    only = ""
    if district_ids is not None:
        only = "AND d.id = ANY(%s)"
        params.append(list(district_ids))
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT d.id,
                   COUNT(a.id),
                   COUNT(a.id) FILTER (WHERE a.status = %s),
                   COUNT(a.id) FILTER (WHERE EXISTS (SELECT 1 FROM {Visit._meta.db_table} v WHERE v.address_id = a.id))
            FROM {table} d
            JOIN {Address._meta.db_table} a
              ON a.organization_id = d.organization_id AND a.disabled_at IS NULL AND ST_Contains(d.geometry, a.location)
            WHERE d.organization_id = %s {only}
            GROUP BY d.id
            """,
            params,
        )
        return {
            pk: {"total": total, "to_visit": to_visit, "done": done, "done_pct": round(100 * done / total, 1) if total else 0}
            for pk, total, to_visit, done in cursor.fetchall()
        }


# --------------------------------------------------------------------------- custom import


def rows_from_custom(geometry_data: bytes, results_data: bytes, results_filename: str, mapping: dict) -> tuple[list[DistrictRow], dict]:
    features = read_geojson(geometry_data)
    df, _ = read_table(results_data, results_filename, mapping.get("sheet"))
    df.columns = [str(c).replace("\n", " ").strip() for c in df.columns]

    def column(key, required=False):
        name = mapping.get(key) or None
        if name is None and required:
            raise DistrictImportError(f"Choisis la colonne « {MAPPING_LABELS[key]} ».")
        if name is not None and name not in df.columns:
            raise DistrictImportError(f"Colonne introuvable dans le fichier des résultats : {name}")
        return name

    res_id, linke, valid = column("res_id", True), column("linke", True), column("valid", True)
    eligible, voters = column("eligible"), column("voters")
    party_columns = [c for c in (mapping.get("parties") or []) if c in df.columns]
    geo_id = mapping.get("geo_id")
    if not geo_id or geo_id not in features[0]:
        raise DistrictImportError("Choisis la propriété qui identifie le bureau dans le fichier des bureaux.")
    geo_name = mapping.get("geo_name") or None

    # Results summed per district: some files have several lines per district (e.g. ballot box + postal).
    results: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    for record in df.to_dict(orient="records"):
        key = normalize_id(record.get(res_id))
        if not key or key == "NAN":
            continue
        for target, col in [("linke", linke), ("valid", valid), ("eligible", eligible), ("voters", voters)]:
            if col and (v := to_number(record.get(col))) is not None:
                results[key][target] += v
        for col in party_columns:
            if (v := to_number(record.get(col))) is not None:
                results[key][f"party:{col}"] += v

    rows, unmatched = [], []
    by_id = merge_by(features, lambda f: normalize_id(f.get(geo_id)))
    seen = set(by_id)
    for key, feature in by_id.items():
        result = results.get(key)
        if result is None:
            unmatched.append(str(feature.get(geo_id)))
        result = result or {}
        name = str(feature.get(geo_name)) if geo_name and feature.get(geo_name) not in (None, "") else f"Bureau {feature.get(geo_id)}"
        rows.append(
            DistrictRow(
                code=str(feature.get(geo_id))[:32],
                name=name,
                geometry=feature["_geometry"],
                eligible=result.get("eligible") if eligible else None,
                voters=result.get("voters") if voters else None,
                valid=result.get("valid"),
                linke=result.get("linke"),
                parties={k[6:]: v for k, v in result.items() if k.startswith("party:")},
            )
        )
    unused = sorted(set(results) - seen)
    report = {
        "n_without_results": len(unmatched),
        "examples_without_results": unmatched[:10],
        "n_results_without_district": len(unused),
        "examples_results_without_district": unused[:10],
    }
    if len(unmatched) == len(rows):
        raise DistrictImportError(
            "Aucun bureau ne correspond aux résultats : vérifie les colonnes d'identifiant choisies "
            f"(exemples côté carte : {', '.join(map(str, [f.get(geo_id) for f in features[:3]]))} ; "
            f"côté résultats : {', '.join(list(results)[:3])})."
        )
    return rows, report


MAPPING_LABELS = {
    "geo_id": "identifiant du bureau (carte)",
    "res_id": "identifiant du bureau (résultats)",
    "linke": "voix Die Linke",
    "valid": "suffrages exprimés",
    "eligible": "inscrit·es",
    "voters": "votant·es",
}


# --------------------------------------------------------------------------- Berlin preset

BERLIN_WFS = (
    "https://gdi.berlin.de/services/wfs/wahlgebiete_agh2026?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
    "&TYPENAMES=wahlgebiete_agh2026:agh2026_uwb&OUTPUTFORMAT=application/json&SRSNAME=EPSG:4326"
)
BERLIN_RESULTS = "https://www.wahlen-berlin.de/wahlen/BE2026/Afspraes/agh/DL/DL_BE_AGHBVV2026.xlsx"
BERLIN_ELECTION = "Abgeordnetenhaus de Berlin, 20/09/2026 (2e voix)"
BERLIN_FIRST_PARTY_COLUMN = "CDU"


def _download(url: str) -> bytes:
    response = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response.content


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
                linke=round(t["Die Linke"], 1),
                parties={p: round(t[p], 1) for p in parties if t[p]},
            )
        )
    report = {"n_without_results": len(unmatched), "examples_without_results": unmatched[:10]}
    return rows, report


PRESETS = {
    "berlin_agh2026": {
        "label": "Berlin — Abgeordnetenhaus 2026",
        "description": "2 542 bureaux de vote, résultats définitifs du 20 septembre 2026 (vote par correspondance inclus).",
    },
}


def run_preset(key: str) -> tuple[list[DistrictRow], dict, str]:
    if key == "berlin_agh2026":
        rows, report = rows_from_berlin(_download(BERLIN_WFS), _download(BERLIN_RESULTS))
        return rows, report, BERLIN_ELECTION
    raise DistrictImportError("Import inconnu.")


# --------------------------------------------------------------------------- background run


def start_import(job: DistrictImport, mapping: dict | None = None) -> None:
    job.status = DistrictImport.ImportStatus.RUNNING
    job.message = ""
    job.save(update_fields=["status", "message"])
    thread = threading.Thread(target=_run, args=(job.id, mapping or {}), daemon=True)
    thread.start()


def _run(job_id: int, mapping: dict) -> None:
    close_old_connections()
    job = DistrictImport.objects.select_related("organization").get(pk=job_id)
    try:
        if job.source == "custom":
            rows, report = rows_from_custom(
                bytes(job.geometry_file), bytes(job.results_file), job.results_filename, mapping
            )
            election = (mapping.get("election") or "").strip()[:128]
        else:
            rows, report, election = run_preset(job.source)
        report.update(save_districts(job.organization, rows, election))
        job.status = DistrictImport.ImportStatus.DONE
        job.report = report
        job.geometry_file = None
        job.results_file = None
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
