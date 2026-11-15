"""Load the 100 m grid of the 2022 German census (population, age, foreigners, rent) into `CensusCell`.

Shared by every organization: run it once for the whole site (or for a bounding box to keep the database small):

    manage.py load_zensus                                  # all of Germany (~3 million cells)
    manage.py load_zensus --bbox 13.08,52.33,13.77,52.68   # Berlin only

Then re-import the polling districts (or click "Recalculer") so that they pick up the census figures.
"""
import csv
import io
import pathlib
import zipfile

import requests
from django.contrib.gis.gdal import CoordTransform, SpatialReference
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

BASE_URL = "https://www.destatis.de/static/DE/zensus/gitterdaten/"
FILES = {
    "population": "Zensus2022_Bevoelkerungszahl.zip",
    "age": "Alter_in_5_Altersklassen.zip",
    "foreign": "Auslaenderanteil_in_Gitterzellen.zip",
    "rent": "Durchschnittliche_Nettokaltmiete_und_Anzahl_der_Wohnungen.zip",
}


def number(value: str) -> float | None:
    value = (value or "").strip()
    if not value or value in {"–", "-", "."}:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


class Command(BaseCommand):
    help = "Load the 2022 census 100 m grid (population, age, foreigners, rent) used to describe polling districts."

    def add_arguments(self, parser):
        parser.add_argument("--bbox", help="min_lon,min_lat,max_lon,max_lat (WGS84). Default: all of Germany.")
        parser.add_argument("--cache-dir", default="/tmp/zensus", help="Where the downloaded ZIP files are kept.")

    def handle(self, *args, **opts):
        cache = pathlib.Path(opts["cache_dir"])
        cache.mkdir(parents=True, exist_ok=True)
        bounds = self.bounds_3035(opts["bbox"]) if opts["bbox"] else None

        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TEMP TABLE z_population (grid_id text PRIMARY KEY, x int, y int, population int) ON COMMIT DROP;
                CREATE TEMP TABLE z_age (grid_id text PRIMARY KEY, known int, a18 int, a65 int) ON COMMIT DROP;
                CREATE TEMP TABLE z_foreign (grid_id text PRIMARY KEY, share float) ON COMMIT DROP;
                CREATE TEMP TABLE z_rent (grid_id text PRIMARY KEY, rent float, dwellings int) ON COMMIT DROP;
                """
            )
            for key, filename in FILES.items():
                path = self.download(cache, filename)
                n = self.copy(cursor, key, path, bounds)
                self.stdout.write(f"{key}: {n} cells")

            where = ""
            params = []
            if bounds:
                where = "WHERE ST_Intersects(point, ST_Transform(ST_MakeEnvelope(%s, %s, %s, %s, 3035), 4326))"
                params = list(bounds)
            cursor.execute(f"DELETE FROM canvassing_censuscell {where}", params)
            cursor.execute(
                """
                INSERT INTO canvassing_censuscell
                    (grid_id, point, population, age_known, age_18_29, age_65_plus, share_foreign, rent_m2, dwellings)
                SELECT p.grid_id,
                       ST_Transform(ST_SetSRID(ST_MakePoint(p.x, p.y), 3035), 4326),
                       p.population,
                       COALESCE(a.known, 0), COALESCE(a.a18, 0), COALESCE(a.a65, 0),
                       f.share, r.rent, r.dwellings
                FROM z_population p
                LEFT JOIN z_age a USING (grid_id)
                LEFT JOIN z_foreign f USING (grid_id)
                LEFT JOIN z_rent r USING (grid_id)
                WHERE p.population > 0
                ON CONFLICT (grid_id) DO UPDATE SET
                    point = EXCLUDED.point, population = EXCLUDED.population, age_known = EXCLUDED.age_known,
                    age_18_29 = EXCLUDED.age_18_29, age_65_plus = EXCLUDED.age_65_plus,
                    share_foreign = EXCLUDED.share_foreign, rent_m2 = EXCLUDED.rent_m2, dwellings = EXCLUDED.dwellings
                """
            )
            self.stdout.write(self.style.SUCCESS(f"{cursor.rowcount} census cells loaded."))
        cursor = connection.cursor()
        cursor.execute("ANALYZE canvassing_censuscell")

    def bounds_3035(self, bbox: str) -> tuple[float, float, float, float]:
        try:
            min_lon, min_lat, max_lon, max_lat = (float(v) for v in bbox.split(","))
        except ValueError:
            raise CommandError("--bbox attend min_lon,min_lat,max_lon,max_lat") from None
        transform = CoordTransform(SpatialReference(4326), SpatialReference(3035))
        xs, ys = [], []
        for lon, lat in [(min_lon, min_lat), (min_lon, max_lat), (max_lon, min_lat), (max_lon, max_lat)]:
            point = Point(lon, lat, srid=4326)
            point.transform(transform)
            xs.append(point.x)
            ys.append(point.y)
        return min(xs), min(ys), max(xs), max(ys)

    def download(self, cache: pathlib.Path, filename: str) -> pathlib.Path:
        path = cache / filename
        if path.exists() and zipfile.is_zipfile(path):
            return path
        self.stdout.write(f"Downloading {filename}…")
        with requests.get(BASE_URL + filename, stream=True, timeout=600) as response:
            response.raise_for_status()
            with open(path, "wb") as fh:
                for chunk in response.iter_content(1 << 20):
                    fh.write(chunk)
        if not zipfile.is_zipfile(path):
            path.unlink()
            raise CommandError(f"{filename}: not a ZIP file (has the census site moved it?)")
        return path

    def copy(self, cursor, key: str, path: pathlib.Path, bounds) -> int:
        with zipfile.ZipFile(path) as archive:
            name = next((n for n in archive.namelist() if n.endswith("100m-Gitter.csv")), None)
            if name is None:
                raise CommandError(f"{path.name}: no 100 m grid file inside")
            with archive.open(name) as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace"), delimiter=";")
                table, columns = {
                    "population": ("z_population", "grid_id, x, y, population"),
                    "age": ("z_age", "grid_id, known, a18, a65"),
                    "foreign": ("z_foreign", "grid_id, share"),
                    "rent": ("z_rent", "grid_id, rent, dwellings"),
                }[key]
                n = 0
                with cursor.cursor.copy(f"COPY {table} ({columns}) FROM STDIN") as copy:
                    for row in reader:
                        x, y = number(row.get("x_mp_100m")), number(row.get("y_mp_100m"))
                        if x is None or y is None:
                            continue
                        if bounds and not (bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]):
                            continue
                        record = self.record(key, row, x, y)
                        if record is not None:
                            copy.write_row(record)
                            n += 1
        return n

    @staticmethod
    def record(key, row, x, y):
        grid_id = row["GITTER_ID_100m"]
        if key == "population":
            population = number(row.get("Einwohner"))
            return None if population is None else (grid_id, int(x), int(y), int(population))
        if key == "age":
            a18, a65 = number(row.get("a18bis29")), number(row.get("a65undaelter"))
            total = number(row.get("Insgesamt_Bevoelkerung"))
            if a18 is None or a65 is None or not total:
                return None
            return (grid_id, int(total), int(a18), int(a65))
        if key == "foreign":
            share = number(row.get("AnteilAuslaender"))
            return None if share is None else (grid_id, share / 100)
        rent, dwellings = number(row.get("durchschnMieteQM")), number(row.get("AnzahlWohnungen"))
        return None if rent is None else (grid_id, rent, int(dwellings or 0))
