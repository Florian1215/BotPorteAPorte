"""Load the share of low-income residents per neighbourhood into `SocialArea`, then update the districts.

Berlin: "Monitoring Soziale Stadtentwicklung 2023" (Senate of Berlin, data of 31 Dec 2022, licence dl-de/zero-2-0),
542 "Planungsräume". Shared by every organization: run it once for the whole site.

    manage.py load_social_index

The census grid (`load_zensus`) should be loaded first: districts take the population-weighted mean of the
neighbourhoods their census cells fall in (without it, the overlapping area is used instead).

Low income = people living on minimum social benefits (Grundsicherung: "Bürgergeld" / SGB II, and SGB XII),
among all residents. The MSS publishes it in two parts with different denominators:
- s3 "Transferbezug": recipients of SGB II / SGB XII who are *not* registered as unemployed, % of residents;
- s1 "Arbeitslosigkeit": unemployed people on SGB II, % of the 15-to-retirement-age residents.
s1 is brought back to all residents with the share of 15-to-retirement-age people in Berlin (WORKING_AGE_SHARE).
"""
import json

import requests
from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Organization
from canvassing.models import District, SocialArea
from canvassing.services import districts as district_service
from canvassing.services import scoring
from canvassing.services.districts import USER_AGENT, as_multipolygon

SOURCE = "berlin_mss_2023"
WFS_URL = (
    "https://gdi.berlin.de/services/wfs/mss_2023?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
    "&TYPENAMES=mss_2023:mss2023_indexind_542&OUTPUTFORMAT=application/json&SRSNAME=EPSG:4326"
)
# Residents aged 15 to the retirement age among all residents of Berlin: about 2/3 (≈ 14 % under 15, ≈ 19 % over 65).
WORKING_AGE_SHARE = 0.68


def low_income_share(properties: dict) -> float | None:
    if not str(properties.get("kom", "")).startswith("gültig"):
        return None  # too few residents, or outlier: not published
    s1, s3 = properties.get("s1"), properties.get("s3")
    if s1 is None or s3 is None or s1 < 0 or s3 < 0:  # -9999: no value
        return None
    return round((s3 + WORKING_AGE_SHARE * s1) / 100, 4)


class Command(BaseCommand):
    help = "Load the share of low-income residents per neighbourhood (Berlin MSS 2023) and update the districts."

    def handle(self, *args, **opts):
        self.stdout.write("Downloading the Berlin MSS 2023…")
        try:
            response = requests.get(WFS_URL, headers={"User-Agent": USER_AGENT}, timeout=300)
            response.raise_for_status()
            features = response.json()["features"]
        except (requests.RequestException, ValueError, KeyError) as exc:
            raise CommandError(f"Téléchargement impossible : {exc}") from None

        areas = []
        for feature in features:
            properties = feature.get("properties") or {}
            if not feature.get("geometry") or not properties.get("plr_id"):
                continue
            geometry = as_multipolygon(GEOSGeometry(json.dumps(feature["geometry"]), srid=4326))
            if geometry is None:
                continue
            areas.append(
                SocialArea(
                    source=SOURCE,
                    code=properties["plr_id"],
                    name=(properties.get("plr_name") or "")[:255],
                    geometry=geometry,
                    population=properties.get("ew"),
                    low_income=low_income_share(properties),
                )
            )
        if not areas:
            raise CommandError("Aucun quartier dans la réponse du service.")

        with transaction.atomic():
            SocialArea.objects.filter(source=SOURCE).delete()
            SocialArea.objects.bulk_create(areas, batch_size=200)
        n_valued = sum(a.low_income is not None for a in areas)
        self.stdout.write(self.style.SUCCESS(f"{len(areas)} neighbourhoods loaded ({n_valued} with a value)."))

        organizations = Organization.objects.filter(
            id__in=District.objects.values("organization_id").distinct()
        )
        for organization in organizations:
            with transaction.atomic():
                n = district_service.add_low_income(organization)
                scoring.rescore_organization(organization)
            self.stdout.write(f"{organization.name}: {n} districts with a low-income share.")
