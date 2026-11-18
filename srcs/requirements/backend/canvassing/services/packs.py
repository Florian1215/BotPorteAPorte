"""City packs: one click imports the electoral map of a city from its official open data.

Each pack downloads, at click time, the zones (polling districts, or neighbourhoods when a city publishes no
polling-district map) and the results of a recent election, joins them and returns `DistrictRow`s. The rest
(saving, census figures, score) is the common `districts.save_districts`.

German cities share one results file: the federal returning officer's results of every polling district of the
2025 Bundestag election (2nd vote). Only ballot-box districts are kept: postal votes are counted in postal
districts whose link to the ballot-box districts is not published (except in Berlin, see `rows_from_berlin`).
The social indicator of German cities is the mean net rent of the 2022 census (`manage.py load_zensus`, for all
of Germany): the lower, the poorer. Berlin has a better one (MSS, `load_social_index`).

Every source was checked on 2026-11-18 (share of districts matched in the comment of each pack). URLs of open
data portals do change: a failing pack says which file could not be downloaded.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import math
import re
import tempfile
import time
import zipfile
from collections import defaultdict
from ctypes import c_void_p
from dataclasses import dataclass, field
from hashlib import sha1
from pathlib import Path
from typing import Callable

import pandas as pd
import requests
from django.contrib.gis.gdal import CoordTransform, DataSource, OGRGeometry, SpatialReference
from django.contrib.gis.gdal.error import GDALException
from django.contrib.gis.geos import GEOSException, GEOSGeometry, MultiPolygon
from django.db import connection

from .districts import (
    BERLIN_ELECTION,
    BERLIN_RESULTS,
    BERLIN_SETTINGS,
    BERLIN_WFS,
    DistrictImportError,
    DistrictRow,
    ImportSettings,
    as_multipolygon,
    rows_from_berlin,
    to_number,
)

log = logging.getLogger(__name__)

# Some portals (Munich) refuse unknown clients: a browser user agent, as a person clicking the link would send.
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
HTTP_TIMEOUT = 300
CACHE_DIR = Path(tempfile.gettempdir()) / "canvassing-packs"
CACHE_SECONDS = 24 * 3600  # several organizations of a country share files (federal results: 6 MB)
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
# Neighbourhood outlines of the cities without a polling-district map, from OpenStreetMap (© OpenStreetMap
# contributors, ODbL), kept in the repository: Overpass is too often down to be called at each import.
# `manage.py pack_areas` rebuilds them.
AREAS_DIR = Path(__file__).resolve().parent.parent / "data" / "pack_areas"

RENT_SETTINGS = dict(social_label="Loyer net moyen (Zensus 2022)", social_higher_is_poorer=False)


# --------------------------------------------------------------------------- downloads


def fetch(url: str, *, data: dict | None = None) -> bytes:
    """GET (or POST `data`) with a day of disk cache and two retries."""
    key = sha1((url + json.dumps(data or {}, sort_keys=True)).encode()).hexdigest()
    path = CACHE_DIR / key
    if path.exists() and time.time() - path.stat().st_mtime < CACHE_SECONDS:
        return path.read_bytes()
    last = None
    for attempt in range(3):
        try:
            headers = {"User-Agent": BROWSER_UA}
            if data is None:
                response = requests.get(url, timeout=HTTP_TIMEOUT, headers=headers)
            else:
                response = requests.post(url, data=data, timeout=HTTP_TIMEOUT, headers=headers)
            response.raise_for_status()
            if "text/html" in response.headers.get("content-type", "") and not url.endswith((".htm", ".html")):
                raise DistrictImportError(f"Le serveur a renvoyé une page web au lieu des données : {url}")
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
            return response.content
        except (requests.RequestException, DistrictImportError) as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise DistrictImportError(f"Téléchargement impossible ({url}) : {last}")


def unzip(data: bytes, name: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            if info.filename == name or info.filename.endswith("/" + name):
                return archive.read(info)
    raise DistrictImportError(f"Fichier « {name} » absent de l'archive téléchargée.")


# --------------------------------------------------------------------------- geometries


def _plain(value):
    if value is None or isinstance(value, (str, int, float)):
        return value
    return str(value)


def read_layer(files: dict[str, bytes], path: str, layer: str | None = None, srid: int | None = None) -> list[dict]:
    """Features of a vector file read with GDAL (GeoJSON, GML, Shapefile, GeoPackage, zipped or not), geometries
    in EPSG:4326 (`_geometry`). `files`: name → content, written side by side (the parts of a shapefile);
    `path`: what GDAL opens (`/vsizip/` paths are relative to that folder). `srid`: when the file does not say."""
    target = SpatialReference(4326)
    features = []
    with tempfile.TemporaryDirectory() as folder:
        for name, content in files.items():
            (Path(folder) / name).write_bytes(content)
        source = path.replace("{dir}", folder) if "{dir}" in path else str(Path(folder) / path)
        try:
            datasource = DataSource(source)
        except GDALException as exc:
            raise DistrictImportError(f"Carte illisible ({path}) : {exc}") from None
        layers = [lyr for lyr in datasource if layer is None or lyr.name == layer]
        if not layers:
            raise DistrictImportError(f"Couche « {layer} » absente de la carte.")
        lyr = layers[0]
        srs = SpatialReference(srid) if srid else (lyr.srs or target)
        transform = CoordTransform(srs, target)
        fields = lyr.fields
        for feature in lyr:
            try:
                geometry = OGRGeometry(feature.geom.wkb, srs=srs)
                geometry.coord_dim = 2
                geometry.transform(transform)
                try:
                    geos = GEOSGeometry(memoryview(bytes(geometry.wkb)), srid=4326)
                except KeyError:  # curved GML types (MultiSurface…) unknown to GEOS
                    geos = GEOSGeometry(memoryview(bytes(_multipolygon(geometry).wkb)), srid=4326)
                geos = as_multipolygon(geos)
            except (GDALException, GEOSException, ValueError, TypeError):
                continue
            if geos is None or geos.empty:
                continue
            features.append({**{f: _plain(feature.get(f)) for f in fields}, "_geometry": geos})
    if not features:
        raise DistrictImportError(f"Aucun polygone dans la carte ({path}).")
    return features


def _multipolygon(geometry: OGRGeometry) -> OGRGeometry:
    """GML surfaces (MultiSurface, CurvePolygon) → MultiPolygon, with GDAL's OGR_G_ForceToMultiPolygon."""
    from django.contrib.gis.gdal.libgdal import lgdal

    clone, force = lgdal.OGR_G_Clone, lgdal.OGR_G_ForceToMultiPolygon
    clone.restype, clone.argtypes = c_void_p, [c_void_p]
    force.restype, force.argtypes = c_void_p, [c_void_p]
    return OGRGeometry(c_void_p(force(clone(geometry.ptr))), srs=geometry.srs)


def union(geometries: list[GEOSGeometry]) -> MultiPolygon:
    merged = geometries[0]
    for g in geometries[1:]:
        merged = merged.union(g)
    return as_multipolygon(merged)


def overpass_areas(query: str) -> list[dict]:
    """Boundary relations from OpenStreetMap (`out geom`) → [{tags…, _geometry}], polygons built by PostGIS."""
    payload = None
    for url in OVERPASS_URLS:
        try:
            response = requests.post(url, data={"data": f"[out:json][timeout:120];{query}out geom;"},
                                     timeout=150, headers={"User-Agent": BROWSER_UA})
            response.raise_for_status()
            payload = response.json()
            break
        except (requests.RequestException, ValueError) as exc:
            log.warning("Overpass %s: %s", url, exc)
    if payload is None:
        raise DistrictImportError("OpenStreetMap (Overpass) ne répond pas : réessaie dans quelques minutes.")
    areas = []
    with connection.cursor() as cursor:
        for element in payload.get("elements", []):
            lines = [
                "(" + ",".join(f"{p['lon']} {p['lat']}" for p in m["geometry"]) + ")"
                for m in element.get("members", [])
                if m.get("type") == "way" and m.get("geometry") and m.get("role") in ("outer", "inner", "")
            ]
            if not lines:
                continue
            cursor.execute(
                "SELECT ST_AsBinary(ST_Multi(ST_BuildArea(ST_LineMerge(ST_GeomFromText(%s, 4326)))))",
                ["MULTILINESTRING(" + ",".join(lines) + ")"],
            )
            wkb = cursor.fetchone()[0]
            if wkb is None:
                continue
            geometry = as_multipolygon(GEOSGeometry(memoryview(bytes(wkb)), srid=4326))
            if geometry and not geometry.empty:
                areas.append({**element.get("tags", {}), "_geometry": geometry})
    if not areas:
        raise DistrictImportError("Aucun quartier trouvé dans OpenStreetMap.")
    return areas


AREA_QUERIES = {
    "darmstadt": 'area["de:amtlicher_gemeindeschluessel"="06411000"]->.a;'
                 'rel(area.a)["boundary"="administrative"]["admin_level"="9"]["ref"];',
    "dresden": 'area["de:amtlicher_gemeindeschluessel"="14612000"]->.a;'
               'rel(area.a)["boundary"="administrative"]["admin_level"="9"];',
    "warszawa": 'rel["boundary"="administrative"]["admin_level"="6"]["name"="Warszawa"];map_to_area->.a;'
                'rel(area.a)["boundary"="administrative"]["admin_level"="9"]["teryt:terc"];',
}
AREA_TAGS = ("name", "ref", "teryt:terc")


def static_areas(name: str) -> list[dict]:
    """The stored neighbourhoods of a city (see `AREAS_DIR`)."""
    from .districts import read_geojson

    return read_geojson((AREAS_DIR / f"{name}.geojson").read_bytes())


def save_areas(name: str) -> int:
    """Download the neighbourhoods of a city from OpenStreetMap and store them, simplified (~10 m)."""
    features = []
    for area in overpass_areas(AREA_QUERIES[name]):
        geometry = area["_geometry"].simplify(0.0001, preserve_topology=True)
        features.append({
            "type": "Feature",
            "properties": {t: area[t] for t in AREA_TAGS if t in area},
            "geometry": json.loads(as_multipolygon(geometry).geojson),
        })
    AREAS_DIR.mkdir(parents=True, exist_ok=True)
    collection = {"type": "FeatureCollection", "attribution": "© OpenStreetMap contributors, ODbL", "features": features}
    (AREAS_DIR / f"{name}.geojson").write_text(json.dumps(collection, ensure_ascii=False, separators=(",", ":")))
    return len(features)


# --------------------------------------------------------------------------- results


def key(value) -> str:
    """District numbers as written in different files: "006-11", "00611", 611 are the same."""
    s = re.sub(r"[^0-9A-Za-z]", "", str(value if value is not None else "")).upper()
    return (s.lstrip("0") or "0") if s.isdigit() else s


@dataclass
class Result:
    eligible: float = 0.0
    voters: float = 0.0
    valid: float = 0.0
    parties: dict = field(default_factory=lambda: defaultdict(float))

    def add(self, other: "Result") -> None:
        self.eligible += other.eligible
        self.voters += other.voters
        self.valid += other.valid
        for party, votes in other.parties.items():
            self.parties[party] += votes


def grouped(results: dict[str, Result], group: Callable[[str], str | None]) -> dict[str, Result]:
    out: dict[str, Result] = defaultdict(Result)
    for k, result in results.items():
        if (g := group(k)) is not None:
            out[g].add(result)
    return dict(out)


@dataclass
class Zone:
    code: str
    name: str
    geometry: MultiPolygon
    members: list[str]  # keys of the results counted in the zone (several when districts share a polling station)


def zones_by(features: list[dict], code: Callable[[dict], str], name: Callable[[dict], str],
             members: Callable[[dict], list[str]] | None = None) -> list[Zone]:
    """One zone per code: features drawn in several pieces (or a neighbourhood made of several districts) merged."""
    by_code: dict[str, list[dict]] = defaultdict(list)
    for feature in features:
        c = code(feature)
        if c:
            by_code[c].append(feature)
    return [
        Zone(c, name(fs[0]), union([f["_geometry"] for f in fs]), members(fs[0]) if members else [c])
        for c, fs in by_code.items()
    ]


def join(zones: list[Zone], results: dict[str, Result]) -> tuple[list[DistrictRow], dict]:
    rows, without = [], []
    used = set()
    for zone in zones:
        total, found = Result(), False
        for member in zone.members:
            if member in results:
                total.add(results[member])
                used.add(member)
                found = True
        if not found:
            without.append(zone.code)
        rows.append(
            DistrictRow(
                code=zone.code[:32],
                name=zone.name,
                geometry=zone.geometry,
                eligible=round(total.eligible, 1) if found else None,
                voters=round(total.voters, 1) if found else None,
                valid=round(total.valid, 1) if found else None,
                # Zeros kept: no vote for the reference party is a 0 %, not a missing value.
                parties={p: round(v, 1) for p, v in total.parties.items()} if found else {},
            )
        )
    matched = len(zones) - len(without)
    if matched < 0.8 * len(zones) or len(used) < 0.8 * len(results):
        raise DistrictImportError(
            f"La carte et les résultats ne correspondent plus ({matched}/{len(zones)} zones avec résultats, "
            f"{len(used)}/{len(results)} résultats placés) : la source a sans doute changé."
        )
    return rows, {
        "n_without_results": len(without),
        "examples_without_results": without[:10],
        "n_results_without_district": len(set(results) - used),
    }


# German federal results by polling district (Bundestag 2025)
BTW25_URL = "https://www.bundeswahlleiterin.de/dam/jcr/e79a7bd3-0607-4e87-9752-8e601e299e00/btw25_wbz.zip"
BTW25_ELECTION = "Bundestagswahl du 23/02/2025 (2e voix, vote à l'urne)"
BTW25_SOURCE = "Die Bundeswahlleiterin – Wahlbezirksstatistik BTW 2025"


def btw25(municipality: str, by: str) -> dict[str, Result]:
    """Ballot-box districts of a municipality (`Gemeindename` prefix, e.g. "Leipzig,"), keyed by
    `by`: "wbz" (district number), "label" (unabridged label) or "anlage30" (first word of the official name)."""
    raw = unzip(fetch(BTW25_URL), "btw25_wbz_ergebnisse.csv").decode("utf-8-sig")
    df = pd.read_csv(io.StringIO(raw), sep=";", skiprows=4, dtype=str)
    df = df[df["Gemeindename"].str.startswith(municipality, na=False) & (df["Bezirksart"] == "0")]
    if df.empty:
        raise DistrictImportError(f"Aucun bureau de « {municipality} » dans les résultats fédéraux.")
    second = [c for c in df.columns if c.endswith(" - Zweitstimmen") and not c.startswith(("Gültige", "Ungültige"))]
    column = {
        "wbz": "Wahlbezirk",
        "label": "Ungekürzte Wahlbezirksbezeichnung",
        "anlage30": "Bezeichnung des Wahlbezirkes gemäß Anlage 30 zur BWO",
    }[by]
    results: dict[str, Result] = {}
    for record in df.to_dict(orient="records"):
        raw_key = str(record[column] or "")
        k = key(raw_key.split()[0] if by == "anlage30" and raw_key.strip() else raw_key)
        r = results.setdefault(k, Result())
        r.add(Result(
            eligible=to_number(record["Wahlberechtigte (A)"]) or 0,
            voters=to_number(record["Wählende (B)"]) or 0,
            valid=to_number(record["Gültige - Zweitstimmen"]) or 0,
            parties=defaultdict(float, {c.removesuffix(" - Zweitstimmen"): to_number(record[c]) or 0 for c in second}),
        ))
    return results


LINKE = ImportSettings(reference_party="Die Linke", reference_party_columns=["Die Linke"], **RENT_SETTINGS)
KPOE = ImportSettings(reference_party="KPÖ", reference_party_columns=["KPÖ"], social_label=None)


# --------------------------------------------------------------------------- packs


@dataclass
class PackResult:
    rows: list[DistrictRow]
    report: dict
    election: str
    settings: ImportSettings
    social_from_rent: bool = False  # German cities: the census rent as social indicator


@dataclass(frozen=True)
class Pack:
    key: str
    city: str
    country: str  # ISO code
    lat: float
    lon: float
    election: str
    level: str  # "bureaux de vote", "quartiers"…
    description: str
    sources: tuple[str, ...]
    build: Callable[[], PackResult]

    def to_dict(self) -> dict:
        return {
            "key": self.key, "city": self.city, "country": self.country, "election": self.election,
            "level": self.level, "description": self.description, "sources": list(self.sources),
            "label": f"{self.city} — {self.election}",
        }


def _german(municipality: str, by: str, zones: Callable[[], list[Zone]], group=None) -> Callable[[], PackResult]:
    def build() -> PackResult:
        results = btw25(municipality, by)
        if group:
            results = grouped(results, group)
        rows, report = join(zones(), results)
        return PackResult(rows, report, BTW25_ELECTION, LINKE, social_from_rent=True)
    return build


def _layer(url: str, filename: str, path: str | None = None, layer: str | None = None, srid: int | None = None):
    return read_layer({filename: fetch(url)}, path or filename, layer, srid)


# ---- Berlin


def build_berlin() -> PackResult:
    rows, report = rows_from_berlin(fetch(BERLIN_WFS), fetch(BERLIN_RESULTS))
    return PackResult(rows, report, BERLIN_ELECTION, BERLIN_SETTINGS)


# ---- Frankfurt am Main: 378/378 districts
FRANKFURT_WFS = (
    "https://geowebdienste.frankfurt.de/WFS_Bundestagswahl_2025?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
    "&TYPENAMES=Wahlgebietsgliederung_Bundestagswahl_2025:BW2025_Urnenwahlbezirke"
)


def frankfurt_zones():
    return zones_by(_layer(FRANKFURT_WFS, "ffm.gml"), lambda f: key(f["UWBZ_ID"]), lambda f: f"Bureau {f['UWBZ_NAME']}")


# ---- Leipzig: 414/414
LEIPZIG_SHP = (
    "https://opendata.leipzig.de/dataset/fea13bec-d397-40d9-b3de-2bd3030fa248/resource/"
    "cb5f3127-9860-4ef8-9375-d5fa3b8c6772/download/leipzig_wahlbezirke_bundestagswahl_2025.zip"
)


def leipzig_zones():
    features = _layer(LEIPZIG_SHP, "leipzig.zip", "/vsizip/{dir}/leipzig.zip")
    return zones_by(features, lambda f: key(f["wbz"]), lambda f: f"Bureau {f['wbz']}")


# ---- Hamburg: 1267/1267 (the 2025 Bürgerschaft and Bundestag districts are the same)
HAMBURG_WFS = (
    "https://geodienste.hamburg.de/HH_WFS_Wahlen?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
    "&TYPENAMES=de.hh.up:wahlbezirke&OUTPUTFORMAT=application/geo%2Bjson&SRSNAME=EPSG:4326"
)


def hamburg_zones():
    features = _layer(HAMBURG_WFS, "hh.geojson")
    return zones_by(features, lambda f: key(f["wahlbezirksnummer"]), lambda f: f"Bureau {f['wahlbezirksnummer']}")


# ---- Nürnberg: 363/363 (shapefile without projection file: Gauss-Krüger zone 4)
NUERNBERG_SHP = "https://www.nuernberg.de/imperia/md/statistik/dokumente/karten/geometrie_btw_2025_wbez.zip"


def nuernberg_zones():
    features = _layer(NUERNBERG_SHP, "nbg.zip", "/vsizip/{dir}/nbg.zip", srid=_nuernberg_srid())
    return zones_by(features, lambda f: key(f["GEB_KENN"]), lambda f: f"{f['GEB_KENN']} ({f['GEB_BEZ']})")


def _nuernberg_srid() -> int:
    return 31468


# ---- Hannover: 331/331
HANNOVER_ZIP = "https://www.hannover.de/content/download/887490/file/SKH5_Wahlen.zip"


def hannover_zones():
    features = _layer(HANNOVER_ZIP, "hann.zip", "/vsizip/{dir}/hann.zip/Wahlbezirke/LHH_Wahlbezirke.shp")
    return zones_by(features, lambda f: key(f["WBZNR"]), lambda f: f"Bureau {f['WBZNR']}")


# ---- München: 470/470 (districts of the 2024 European election, unchanged for the 2025 Bundestag)
MUENCHEN_ZIP = (
    "https://opendata.muenchen.de/dataset/9b645b5a-6c99-4a34-a442-29a0dab52d29/resource/"
    "fab80e14-8cf5-4ba4-a2cf-11400dcca85b/download/euw2024_stimmbezirke.zip"
)


def muenchen_zones():
    features = _layer(MUENCHEN_ZIP, "muc.zip", "/vsizip/{dir}/muc.zip")
    return zones_by(features, lambda f: key(f["BEZEICHNUN"]), lambda f: f"Stimmbezirk {f['BEZEICHNUN']}")


# ---- Bremen: 347/347 (the 2020 districts, used until the 2026 redistricting)
BREMEN_WFS = (
    "https://geodienste.bremen.de/wfs_wahlbezirke2020?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
    "&TYPENAMES=app:wahlbezirke_2020_der_stadtgemeinde_bremen"
)


def bremen_zones():
    features = _layer(BREMEN_WFS, "hb.gml", srid=25832)
    return zones_by(features, lambda f: key(f["wbz"]), lambda f: f"{f['bez_gem']} – {f['wbz']}")


# ---- Kiel: 137/137 districts in 107 zones (districts sharing a polling station are drawn together: "011/015")
KIEL_WFS = (
    "https://ims.kiel.de/geodatenextern/services/Stadtplan/LHKielWmsWfs/MapServer/WFSServer"
    "?request=GetFeature&service=WFS&typeName=Wahlbezirke&outputFormat=geoJSON"
)


def kiel_zones():
    features = _layer(KIEL_WFS, "kiel.geojson")
    return zones_by(
        features,
        lambda f: str(f["Wahlbezirk"]).strip(),
        lambda f: f"{str(f['Wahlbezirk']).strip()} – {str(f.get('Wahllokal') or '').strip()}".strip(" –"),
        members=lambda f: [key(p) for p in str(f["Wahlbezirk"]).split("/")],
    )


# ---- Stuttgart: 265/265
STUTTGART_GPKG = (
    "https://opendata.stuttgart.de/dataset/eaf4abe3-03ee-4553-b0d6-50873e6d1998/resource/"
    "548c58ac-c427-4d06-a734-503bd19103ee/download/wbz_btw25.gpkg"
)


def stuttgart_zones():
    features = _layer(STUTTGART_GPKG, "stuttgart.gpkg")
    return zones_by(features, lambda f: key(f["AWBEZ_T"]), lambda f: f"{f['STBNAM_T']} – {f['AWBEZ_T']}")


# ---- Freiburg: 138/139
FREIBURG_WFS = (
    "https://geoportal.freiburg.de/wfs/abi_wahl/abi_wahl?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
    "&TYPENAMES=ms:wahlbezirke_2025"
)


def freiburg_zones():
    features = _layer(FREIBURG_WFS, "freiburg.gml")
    return zones_by(features, lambda f: key(f["wbz"]), lambda f: f"Bureau {str(f['wbz'])[:3]}-{str(f['wbz'])[3:]}")


# ---- Karlsruhe: no map of the 2025 districts → its 27 Stadtteile (from the 2021 district map, whose numbers
# begin with the Stadtteil: "1021" = Stadtteil 10, district 21; 2025: "010-21").
KARLSRUHE_GEOJSON = (
    "https://transparenz.karlsruhe.de/dataset/61eaf3b7-5e8c-4742-be4b-4068cd9e901c/resource/"
    "77edb714-6b50-4fc3-98f3-5559bcdff20f/download/wahlbezirke.geojson"
)
KARLSRUHE_STADTTEILE = {
    1: "Innenstadt-Ost", 2: "Innenstadt-West", 3: "Südstadt", 4: "Südweststadt", 5: "Weststadt",
    6: "Nordweststadt", 7: "Oststadt", 8: "Mühlburg", 9: "Daxlanden", 10: "Knielingen", 11: "Grünwinkel",
    12: "Oberreut", 13: "Beiertheim-Bulach", 14: "Weiherfeld-Dammerstock", 15: "Rüppurr", 16: "Waldstadt",
    17: "Rintheim", 18: "Hagsfeld", 19: "Durlach", 20: "Grötzingen", 21: "Stupferich", 22: "Hohenwettersbach",
    23: "Wolfartsweier", 24: "Grünwettersbach", 25: "Palmbach", 26: "Neureut", 27: "Nordstadt",
}


def karlsruhe_zones():
    features = _layer(KARLSRUHE_GEOJSON, "karlsruhe.geojson")
    def stadtteil(f) -> str:
        number = str(f.get("Wahlbezirk") or "").strip()
        return str(int(number[:-2] or 0)) if number.isdigit() else ""

    return zones_by(features, stadtteil, lambda f: KARLSRUHE_STADTTEILE.get(int(stadtteil(f)), f"Stadtteil {stadtteil(f)}"))


def karlsruhe_group(k: str) -> str:
    return str(int(k[:-2] or 0))  # "1021" (from "010-21") → "10"


# ---- Darmstadt: no map of the districts → its 9 Stadtteile from OpenStreetMap (ref "100"…"900"); the district
# numbers begin with the Stadtteil ("411" → 400).
def darmstadt_zones():
    return zones_by(static_areas("darmstadt"), lambda a: str(a["ref"])[0], lambda a: a["name"])


# ---- Dresden: no map of the districts → its 10 Stadtbezirke and 9 Ortschaften from OpenStreetMap. The district
# numbers begin with the statistical Stadtteil (2 digits); the first one is the Stadtbezirk.
DRESDEN_BEZIRKE = {
    "0": "Altstadt", "1": "Neustadt", "2": "Pieschen", "3": "Klotzsche", "4": "Loschwitz", "5": "Blasewitz",
    "6": "Leuben", "7": "Prohlis", "8": "Plauen", "9": "Cotta",
}
DRESDEN_ORTSCHAFTEN = {"35": "Weixdorf", "36": "Langebrück", "45": "Schönfeld-Weißig"}


def dresden_zones():
    return zones_by(static_areas("dresden"), lambda a: a.get("name"), lambda a: a["name"])


def dresden_group_from_labels() -> Callable[[str], str | None]:
    """District number ("83300", unabridged label) → its Stadtbezirk or Ortschaft (OSM name). Ortschaften made
    of several villages share a Stadtteil number: their name in the official label decides."""
    raw = unzip(fetch(BTW25_URL), "btw25_wbz_ergebnisse.csv").decode("utf-8-sig")
    df = pd.read_csv(io.StringIO(raw), sep=";", skiprows=4, dtype=str)
    df = df[df["Gemeindename"].str.startswith("Dresden,", na=False) & (df["Bezirksart"] == "0")]
    names = {key(r["Ungekürzte Wahlbezirksbezeichnung"]): str(r["Bezeichnung des Wahlbezirkes gemäß Anlage 30 zur BWO"])
             for r in df.to_dict(orient="records")}

    def group(k: str) -> str | None:
        code = k.zfill(5)
        label = names.get(k, "")
        for village in ("Schönborn", "Oberwartha", "Mobschatz", "Altfranken", "Gompitz", "Cossebaude"):
            if village in label:
                return village
        if code[:2] in DRESDEN_ORTSCHAFTEN:
            return DRESDEN_ORTSCHAFTEN[code[:2]]
        if code[:2] == "90":
            return "Cossebaude"
        if code[:2] == "99":
            return "Gompitz"
        return DRESDEN_BEZIRKE.get(code[0])
    return group


def build_dresden() -> PackResult:
    results = grouped(btw25("Dresden,", "label"), dresden_group_from_labels())
    rows, report = join(dresden_zones(), results)
    return PackResult(rows, report, BTW25_ELECTION, LINKE, social_from_rent=True)


# ---- Wien: 1504 Sprengel, one file with the outlines and the results of the 2025 municipal election
WIEN_WFS = (
    "https://data.wien.gv.at/daten/geo?service=WFS&request=GetFeature&version=1.1.0"
    "&typeName=ogdwien:WAHLERGEBNISGR251OGD&srsName=EPSG:4326&outputFormat=json"
)


def build_wien() -> PackResult:
    features = _layer(WIEN_WFS, "wien.json", srid=4326)
    zones, results = [], {}
    for f in features:
        code = str(f["SPRENGEL_KURZ"])
        parties = {}
        for column in f:
            if column.endswith("_STIMMEN") and f.get(column.removesuffix("_STIMMEN") + "_NAMEKURZ"):
                parties[f[column.removesuffix("_STIMMEN") + "_NAMEKURZ"]] = to_number(f[column]) or 0
        results[code] = Result(
            eligible=to_number(f["ANZAHLWAHLBERECHTIGTE"]) or 0, voters=to_number(f["ABGEGEBENESTIMMEN"]) or 0,
            valid=to_number(f["GUELTIGESTIMMEN"]) or 0, parties=defaultdict(float, parties),
        )
        zones.append(f | {"code": code})
    rows, report = join(
        zones_by(zones, lambda f: f["code"], lambda f: f"{int(f['BEZ'])}. Bezirk – Sprengel {f['SPRENGELNUMMER']}"),
        results,
    )
    return PackResult(rows, report, "Gemeinderatswahl de Vienne du 27/04/2025", KPOE)


# ---- Linz: 215 Sprengel, 2024 national election
LINZ_BASE = "https://data.linz.gv.at/katalog/population/wahlen/"
LINZ_SHP = LINZ_BASE + "wahlsprengelgrenzen/2024/WSPR_2024_NR_WAHL."
LINZ_RESULTS = LINZ_BASE + "nationalsratswahl/2024/NR24Sprengel.csv"


def build_linz() -> PackResult:
    files = {f"linz.{ext}": fetch(LINZ_SHP + ext) for ext in ("shp", "shx", "dbf", "prj")}
    zones = zones_by(read_layer(files, "linz.shp"), lambda f: key(f["WSPRID"]), lambda f: f"Sprengel {f['WSPRID']}")
    raw = fetch(LINZ_RESULTS)
    text = raw.decode("utf-8-sig") if raw[:3] == b"\xef\xbb\xbf" else raw.decode("cp1252")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    fixed = {"Wahl", "Wahlsprengel", "Wahlberechtigte", "abgegebene Stimmen", "gültige Stimmen"}
    results = {}
    for record in reader:
        results[key(record["Wahlsprengel"])] = Result(
            eligible=to_number(record["Wahlberechtigte"]) or 0, voters=to_number(record["abgegebene Stimmen"]) or 0,
            valid=to_number(record["gültige Stimmen"]) or 0,
            parties=defaultdict(float, {p: to_number(v) or 0 for p, v in record.items() if p not in fixed and p}),
        )
    rows, report = join(zones, results)
    return PackResult(rows, report, "Nationalratswahl du 29/09/2024", KPOE)


# ---- Graz: the city publishes the 2026 municipal results by Bezirk only → 17 zones (Sprengel 2026 merged)
GRAZ_SHP = (
    "https://geodaten.graz.at/webshare/OGD/Kategorien/Regierung_Oeffentlicher_Sektor/SHP/"
    "Wahlsprengelgrenzen_2026_Graz_GR.zip"
)
GRAZ_RESULTS = "https://magistratwahlenstorage.blob.core.windows.net/results/GR2026.json"


def build_graz() -> PackResult:
    data = json.loads(fetch(GRAZ_RESULTS))
    results, names = {}, {}
    for bezirk, entry in data.items():
        if not re.fullmatch(r"\d{2}", bezirk):  # postal votes, city total
            continue
        current = entry.get("wahlAktuell") or {}
        votes = current.get("stimmen") or {}
        results[bezirk] = Result(
            eligible=to_number(current.get("wahlberechtigte")) or 0, voters=to_number(votes.get("gesamt")) or 0,
            valid=to_number(votes.get("gueltig")) or 0,
            parties=defaultdict(float, {p["ptname"]: to_number(p.get("stimmen")) or 0 for p in entry.get("ergebnisse") or []}),
        )
        names[bezirk] = re.sub(r"^\d+\s*", "", str(entry.get("titel") or bezirk))
    features = _layer(GRAZ_SHP, "graz.zip", "/vsizip/{dir}/graz.zip")
    bezirk = lambda f: str(f["WSPR"]).strip()[:-2].zfill(2)  # noqa: E731 - "1003" → Bezirk 10
    rows, report = join(zones_by(features, bezirk, lambda f: names.get(bezirk(f), f"Bezirk {bezirk(f)}")), results)
    return PackResult(rows, report, "Gemeinderatswahl de Graz du 28/06/2026 (par arrondissement)", KPOE)


# ---- Praha: 1119/1120 okrsky, 2025 Chamber of Deputies (RÚIAN map of the polling districts)
PRAHA_RUIAN = "https://services.cuzk.cz/shp/obec/epsg-5514/554782.zip"
CZ_PS2025 = "https://volby.gov.cz/opendata/ps2025/"


def build_praha() -> PackResult:
    archive = fetch(PRAHA_RUIAN)
    files = {"praha.zip": archive}
    parts = read_layer(files, "/vsizip/{dir}/praha.zip/554782/MOMC_P.shp")
    momc = {str(p.get("KOD")): str(p.get("NAZEV") or "") for p in parts}
    features = read_layer(files, "/vsizip/{dir}/praha.zip/554782/VO_P.shp")
    zones = zones_by(
        features, lambda f: f"{f['MOMC_KOD']}-{f['CISLO']}",
        lambda f: f"{momc.get(str(f['MOMC_KOD'])) or 'Praha'} – okrsek {f['CISLO']}",
    )
    data = fetch(CZ_PS2025 + "PS2025data20251005_csv.zip")
    parties = {
        r["KSTRANA"]: r["ZKRATKAK8"].strip()
        for r in csv.DictReader(io.StringIO(unzip(fetch(CZ_PS2025 + "PS2025reg20251005_csv.zip"), "csv_od/psrkl.csv").decode("utf-8-sig")))
    }
    totals = pd.read_csv(io.BytesIO(unzip(data, "csv_od/pst4.csv")), dtype=str)
    totals = totals[totals["OKRES"] == "1100"]
    results = {
        f"{r['OBEC']}-{r['OKRSEK']}": Result(
            eligible=to_number(r["VOL_SEZNAM"]) or 0, voters=to_number(r["ODEVZ_OBAL"]) or 0,
            valid=to_number(r["PL_HL_CELK"]) or 0,
        )
        for r in totals.to_dict(orient="records")
    }
    votes = pd.read_csv(io.BytesIO(unzip(data, "csv_od/pst4p.csv")), dtype=str, usecols=["OKRES", "OBEC", "OKRSEK", "KSTRANA", "POC_HLASU"])
    votes = votes[votes["OKRES"] == "1100"]
    for r in votes.to_dict(orient="records"):
        k = f"{r['OBEC']}-{r['OKRSEK']}"
        if k in results:
            results[k].parties[parties.get(r["KSTRANA"], r["KSTRANA"])] += to_number(r["POC_HLASU"]) or 0
    rows, report = join(zones, results)
    settings = ImportSettings(reference_party="Stačilo!", reference_party_columns=["Stačilo!"], social_label=None)
    return PackResult(rows, report, "Élections à la Chambre des députés, 3–4/10/2025", settings)


# ---- Warszawa: no map of the obwody → its 18 dzielnice (OpenStreetMap), 2023 Sejm election
PL_SEJM2023 = "https://wybory.gov.pl/sejmsenat2023/data/csv/wyniki_gl_na_listy_po_obwodach_sejm_csv.zip"
PL_PREFIXES = ("KOALICYJNY KOMITET WYBORCZY ", "KOMITET WYBORCZY WYBORCÓW ", "KOMITET WYBORCZY ")
PL_SHORT = {
    "NOWA LEWICA": "Lewica", "KOALICJA OBYWATELSKA": "Koalicja Obywatelska", "PRAWO I SPRAWIEDLIWOŚĆ": "PiS",
    "TRZECIA DROGA": "Trzecia Droga", "KONFEDERACJA": "Konfederacja", "BEZPARTYJNI SAMORZĄDOWCY": "Bezpartyjni Samorządowcy",
}


def build_warszawa() -> PackResult:
    zones = zones_by(static_areas("warszawa"), lambda a: str(a["teryt:terc"])[:6], lambda a: a["name"])
    archive = fetch(PL_SEJM2023)
    name = next(n for n in zipfile.ZipFile(io.BytesIO(archive)).namelist() if n.endswith(".csv"))
    df = pd.read_csv(io.BytesIO(unzip(archive, name)), sep=";", dtype=str, encoding="utf-8-sig")
    df = df[(df["Powiat"] == "Warszawa") & df["TERYT Gminy"].str.startswith("1465", na=False)]
    committees = [c for c in df.columns if c.startswith(PL_PREFIXES)]

    def short(column: str) -> str:
        for prefix in PL_PREFIXES:
            column = column.removeprefix(prefix)
        for start, name in PL_SHORT.items():
            if column.startswith(start):
                return name
        return column.title() if column.isupper() else column

    results: dict[str, Result] = defaultdict(Result)
    for r in df.to_dict(orient="records"):
        results[str(r["TERYT Gminy"])[:6]].add(Result(
            eligible=to_number(r["Liczba wyborców uprawnionych do głosowania"]) or 0,
            voters=to_number(r["Liczba kart ważnych"]) or 0,
            valid=to_number(r["Liczba głosów ważnych oddanych łącznie na wszystkie listy kandydatów"]) or 0,
            parties=defaultdict(float, {short(c): to_number(r[c]) or 0 for c in committees}),
        ))
    rows, report = join(zones, dict(results))
    settings = ImportSettings(reference_party="Lewica (avec Razem)", reference_party_columns=["Lewica"], social_label=None)
    return PackResult(rows, report, "Élections au Sejm du 15/10/2023 (par arrondissement)", settings)


GERMAN = "bureaux de vote"
PACKS: dict[str, Pack] = {
    p.key: p
    for p in [
        Pack("berlin_agh2026", "Berlin", "DE", 52.52, 13.405, "Abgeordnetenhaus 2026", GERMAN,
             "2 542 bureaux, résultats définitifs du 20/09/2026 (vote par correspondance inclus), indicateur social MSS.",
             ("Amt für Statistik Berlin-Brandenburg",), build_berlin),
        Pack("bremen_btw25", "Brême", "DE", 53.0793, 8.8017, "Bundestag 2025", GERMAN,
             "347 bureaux de vote (vote à l'urne), Die Linke en parti de référence.",
             (BTW25_SOURCE, "GeoInformation Bremen"), _german("Bremen, Stadt", "wbz", bremen_zones)),
        Pack("darmstadt_btw25", "Darmstadt", "DE", 49.8728, 8.6512, "Bundestag 2025", "quartiers",
             "9 quartiers (la ville ne publie pas la carte de ses 99 bureaux), contours OpenStreetMap.",
             (BTW25_SOURCE, "OpenStreetMap"),
             _german("Darmstadt,", "label", darmstadt_zones, group=lambda k: k.zfill(3)[0])),
        Pack("frankfurt_btw25", "Francfort-sur-le-Main", "DE", 50.1109, 8.6821, "Bundestag 2025", GERMAN,
             "378 bureaux de vote (vote à l'urne).",
             (BTW25_SOURCE, "Stadt Frankfurt – Bürgeramt, Statistik und Wahlen"),
             _german("Frankfurt am Main,", "wbz", frankfurt_zones)),
        Pack("dresden_btw25", "Dresde", "DE", 51.0504, 13.7373, "Bundestag 2025", "quartiers",
             "19 arrondissements et localités (la ville ne publie pas la carte de ses 399 bureaux).",
             (BTW25_SOURCE, "OpenStreetMap"), build_dresden),
        Pack("leipzig_btw25", "Leipzig", "DE", 51.3397, 12.3731, "Bundestag 2025", GERMAN,
             "414 bureaux de vote (vote à l'urne).",
             (BTW25_SOURCE, "Stadt Leipzig – Open Data"), _german("Leipzig,", "label", leipzig_zones)),
        Pack("freiburg_btw25", "Fribourg-en-Brisgau", "DE", 47.999, 7.8421, "Bundestag 2025", GERMAN,
             "139 bureaux de vote (vote à l'urne).",
             (BTW25_SOURCE, "Stadt Freiburg – FreiGIS"), _german("Freiburg im Breisgau,", "anlage30", freiburg_zones)),
        Pack("karlsruhe_btw25", "Karlsruhe", "DE", 49.0069, 8.4037, "Bundestag 2025", "quartiers",
             "27 quartiers (Stadtteile) : la carte des bureaux 2025 n'est pas publiée.",
             (BTW25_SOURCE, "Stadt Karlsruhe – Transparenzportal"),
             _german("Karlsruhe,", "anlage30", karlsruhe_zones, group=karlsruhe_group)),
        Pack("stuttgart_btw25", "Stuttgart", "DE", 48.7758, 9.1829, "Bundestag 2025", GERMAN,
             "265 bureaux de vote (vote à l'urne).",
             (BTW25_SOURCE, "Landeshauptstadt Stuttgart – Open Data"), _german("Stuttgart,", "anlage30", stuttgart_zones)),
        Pack("hamburg_btw25", "Hambourg", "DE", 53.5511, 9.9937, "Bundestag 2025", GERMAN,
             "1 267 bureaux de vote (vote à l'urne).",
             (BTW25_SOURCE, "LGV Hamburg"), _german("Hamburg,", "wbz", hamburg_zones)),
        Pack("hannover_btw25", "Hanovre", "DE", 52.3759, 9.732, "Bundestag 2025", GERMAN,
             "331 bureaux de vote (vote à l'urne).",
             (BTW25_SOURCE, "Landeshauptstadt Hannover – Open GeoData"), _german("Hannover,", "wbz", hannover_zones)),
        Pack("kiel_btw25", "Kiel", "DE", 54.3233, 10.1228, "Bundestag 2025", GERMAN,
             "137 bureaux regroupés en 107 zones (bureaux partageant un même lieu de vote).",
             (BTW25_SOURCE, "Landeshauptstadt Kiel – Open Data"), _german("Kiel,", "wbz", kiel_zones)),
        Pack("muenchen_btw25", "Munich", "DE", 48.1351, 11.582, "Bundestag 2025", GERMAN,
             "470 bureaux de vote (vote à l'urne).",
             (BTW25_SOURCE, "Landeshauptstadt München – Open Data"),
             _german("München, Landeshauptstadt", "wbz", muenchen_zones)),
        Pack("nuernberg_btw25", "Nuremberg", "DE", 49.4521, 11.0767, "Bundestag 2025", GERMAN,
             "363 bureaux de vote (vote à l'urne).",
             (BTW25_SOURCE, "Stadt Nürnberg – Amt für Stadtforschung und Statistik"),
             _german("Nürnberg", "wbz", nuernberg_zones)),
        Pack("linz_nr2024", "Linz", "AT", 48.3069, 14.2858, "Nationalrat 2024", GERMAN,
             "215 bureaux (Wahlsprengel), KPÖ en parti de référence.",
             ("Stadt Linz – Open Data",), build_linz),
        Pack("graz_gr2026", "Graz", "AT", 47.0707, 15.4395, "municipales 2026", "arrondissements",
             "17 arrondissements (la ville ne publie les résultats que par arrondissement), KPÖ en parti de référence.",
             ("Stadt Graz – wahlergebnis.graz.at", "Stadt Graz – Open Government Data"), build_graz),
        Pack("wien_gr2025", "Vienne", "AT", 48.2082, 16.3738, "municipales 2025", GERMAN,
             "1 504 bureaux (Wahlsprengel), KPÖ en parti de référence.",
             ("Stadt Wien – data.wien.gv.at",), build_wien),
        Pack("warszawa_sejm2023", "Varsovie", "PL", 52.2297, 21.0122, "Sejm 2023", "arrondissements",
             "18 arrondissements (dzielnice) : les contours des bureaux ne sont pas publiés. Lewica (dont Razem) en parti de référence.",
             ("Państwowa Komisja Wyborcza", "OpenStreetMap"), build_warszawa),
        Pack("praha_ps2025", "Prague", "CZ", 50.0755, 14.4378, "Chambre des députés 2025", GERMAN,
             "1 120 bureaux (volební okrsky), Stačilo! en parti de référence (modifiable).",
             ("Český statistický úřad – volby.gov.cz", "ČÚZK – RÚIAN"), build_praha),
    ]
}


def nearest(lat: float | None, lon: float | None, max_km: float = 40) -> str | None:
    """The pack of the city an organization is in (its city centre within `max_km`)."""
    if lat is None or lon is None:
        return None
    best, best_km = None, max_km
    for pack in PACKS.values():
        km = 6371 * 2 * math.asin(math.sqrt(
            math.sin(math.radians(pack.lat - lat) / 2) ** 2
            + math.cos(math.radians(lat)) * math.cos(math.radians(pack.lat)) * math.sin(math.radians(pack.lon - lon) / 2) ** 2
        ))
        if km < best_km:
            best, best_km = pack.key, km
    return best


def catalog(organization=None) -> list[dict]:
    """The packs, the one of the organization's city first."""
    mine = nearest(getattr(organization, "city_lat", None), getattr(organization, "city_lon", None))
    packs = sorted(PACKS.values(), key=lambda p: (p.key != mine, p.city))
    return [{**p.to_dict(), "recommended": p.key == mine} for p in packs]


def run(key_: str) -> PackResult:
    pack = PACKS.get(key_)
    if pack is None:
        raise DistrictImportError("Pack inconnu.")
    result = pack.build()
    result.report = {**result.report, "pack": pack.key, "level": pack.level, "sources": list(pack.sources)}
    return result


def social_from_rent(organization) -> int:
    """German packs: the census mean net rent of each district as social indicator (the lower, the poorer)."""
    from ..models import District

    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {District._meta.db_table} SET social_value = rent_m2 WHERE organization_id = %s",
            [organization.id],
        )
        cursor.execute(
            f"SELECT COUNT(*) FROM {District._meta.db_table} WHERE organization_id = %s AND social_value IS NOT NULL",
            [organization.id],
        )
        return cursor.fetchone()[0]
