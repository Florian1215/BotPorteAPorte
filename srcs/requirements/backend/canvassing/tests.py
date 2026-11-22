import io
import json
import zipfile
from unittest import mock

import pandas as pd
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.test import SimpleTestCase, TestCase, override_settings

from accounts.models import Organization, VoterList

from .models import District
from .services import districts as ds
from .services import packs
from .services import scoring


def square(x, y, size=0.01):
    return Polygon(((x, y), (x + size, y), (x + size, y + size), (x, y + size), (x, y)), srid=4326)


def feature(props, x, y):
    return {"type": "Feature", "properties": props, "geometry": json.loads(square(x, y).geojson)}


class ScoringTests(SimpleTestCase):
    def test_percentile_ranks_handle_ties(self):
        self.assertEqual(scoring.percentile_ranks({1: 10, 2: 20, 3: 20, 4: 30}), {1: 0, 2: 0.5, 3: 0.5, 4: 1})

    def test_score_is_weighted_mean_of_ranks_and_skips_missing_data(self):
        a = District(id=1, reference_votes=10, valid=100, voters=50, eligible=100, rent_m2=None)
        b = District(id=2, reference_votes=40, valid=100, voters=80, eligible=100, rent_m2=None)
        scoring.compute_scores([a, b], {"party": 50, "abstention": 50, "age": 0, "density": 0, "social": 30})
        # b: best Linke vote (rank 1) but least abstention (rank 0); income is missing everywhere → ignored.
        self.assertEqual(a.score, 50)
        self.assertEqual(b.score, 50)
        scoring.compute_scores([a, b], {"party": 100, "abstention": 0, "age": 0, "density": 0, "social": 0})
        self.assertEqual((a.score, b.score), (0, 100))
        self.assertIsNone(a.score_parts["social"]["rank"])

    def test_more_low_income_is_better(self):
        a, b = District(id=1, social_value=0.25), District(id=2, social_value=0.05)
        scoring.compute_scores([a, b], {"social": 10})
        self.assertGreater(a.score, b.score)

    def test_a_higher_income_is_worse(self):
        a, b = District(id=1, social_value=30000), District(id=2, social_value=18000)
        org = Organization(social_label="Revenu médian", social_higher_is_poorer=False)
        scoring.compute_scores([a, b], {"social": 10}, scoring.criteria_for(org))
        self.assertGreater(b.score, a.score)
        self.assertEqual(scoring.criteria_for(Organization(reference_party="KPÖ"))[0].label, "Vote KPÖ")

    def test_mss_low_income_share(self):
        from canvassing.management.commands.load_social_index import WORKING_AGE_SHARE, low_income_share

        self.assertAlmostEqual(low_income_share({"kom": "gültig", "s1": 5, "s3": 10}), (10 + WORKING_AGE_SHARE * 5) / 100)
        self.assertIsNone(low_income_share({"kom": "ungültig (EW unter 300)", "s1": 5, "s3": 10}))
        self.assertIsNone(low_income_share({"kom": "gültig", "s1": -9999, "s3": 10}))

    def test_clean_weights(self):
        self.assertEqual(scoring.clean_weights({"party": "150", "age": -3})["party"], 100)
        with self.assertRaises(ValueError):
            scoring.clean_weights({})


class HelpersTests(SimpleTestCase):
    def test_normalize_id(self):
        self.assertEqual(ds.normalize_id("01127"), ds.normalize_id(1127))
        self.assertEqual(ds.normalize_id("1127.0"), "1127")
        self.assertEqual(ds.normalize_id(" 1a "), "1A")

    def test_to_number(self):
        self.assertEqual(ds.to_number("1.234,5"), 1234.5)
        self.assertEqual(ds.to_number("12,5"), 12.5)
        self.assertIsNone(ds.to_number("–"))


def berlin_results(rows):
    columns = [
        "Stimmart", "Adresse", "Bezirksnummer", "Bezirksname", "Wahlbezirk", "Wahlbezirksart", "Briefwahlbezirk",
        "Wahlberechtigte insgesamt", "Wahlberechtigte A2", "Wählende", "Gültige Stimmen", "CDU", "Die Linke",
    ]
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        pd.DataFrame(rows, columns=columns).to_excel(writer, sheet_name="AGH_W2", index=False)
    return buffer.getvalue()


class BerlinPostalVotesTests(SimpleTestCase):
    def test_postal_votes_are_shared_in_proportion_to_postal_voters(self):
        geometry = json.dumps(
            {"type": "FeatureCollection", "features": [feature({"uwb": "01101"}, 0, 0), feature({"uwb": "01102"}, 1, 0)]}
        ).encode()
        results = berlin_results(
            [
                # ballot-box districts 101 and 102, both in postal district 1A; 102 has 3× more postal voters
                ["Z", "", 1, "Mitte", 101, "W", "1A", 400, 100, 200, 200, 100, 100],
                ["Z", "", 1, "Mitte", 102, "W", "1A", 400, 300, 100, 100, 50, 50],
                ["Z", "", 1, "Mitte", "1A", "B", "1A", 0, 0, 400, 400, 200, 200],
            ]
        )
        rows, report = ds.rows_from_berlin(geometry, results)
        by_code = {r.code: r for r in rows}
        self.assertEqual(report["n_without_results"], 0)
        self.assertEqual(by_code["01101"].reference_votes, 100 + 50)
        self.assertEqual(by_code["01102"].reference_votes, 50 + 150)
        self.assertEqual(by_code["01102"].voters, 100 + 300)
        self.assertEqual(sum(r.reference_votes for r in rows), 100 + 50 + 200)


def btw25_zip(rows):
    """A federal results file (`btw25_wbz.zip`) with the given ballot-box districts: (municipality, wbz, label,
    Anlage-30 name, eligible, voters, valid, Linke, SPD), plus one postal district that must be left out."""
    header = (
        "Wahlkreis;Land;Regierungsbezirk;Kreis;Verbandsgemeinde;Gemeinde;Kennziffer Urnenwahlbezirke nach § 68 BWO;"
        "Kennziffer Briefwahlzugehörigkeit;Gemeindename;Wahlbezirk;Bezirksart;Wahlberechtigte (A);Wählende (B);"
        "Ungültige - Zweitstimmen;Gültige - Zweitstimmen;Die Linke - Zweitstimmen;SPD - Zweitstimmen;"
        "Ungekürzte Wahlbezirksbezeichnung;Bezeichnung des Wahlbezirkes gemäß Anlage 30 zur BWO"
    )
    lines = ["(c) Die Bundeswahlleiterin", "", "Ergebnisse", "", header]
    for m, wbz, label, name, eligible, voters, valid, linke, spd in rows:
        lines.append(f"1;01;0;02;0000;000;0000;00;{m};{wbz};0;{eligible};{voters};0;{valid};{linke};{spd};{label};{name}")
    lines.append(f"1;01;0;02;0000;000;0000;00;{rows[0][0]};9001;5;0;500;0;500;400;100;9001;Briefwahl")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("btw25_wbz_ergebnisse.csv", "\ufeff" + "\n".join(lines))
    return buffer.getvalue()


class PackTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(code="kiel", name="Kiel", city="Kiel", city_lat=54.32, city_lon=10.13)
        self.federal = btw25_zip([
            ("Kiel, Landeshauptstadt", "000011", "000011", "–", 1000, 600, 590, 120, 100),
            ("Kiel, Landeshauptstadt", "000015", "000015", "–", 500, 300, 290, 10, 100),
            ("Kiel, Landeshauptstadt", "000012", "000012", "–", 800, 400, 400, 20, 200),
            ("Kielholm", "000013", "000013", "–", 1, 1, 1, 1, 0),  # another municipality
        ])

    def test_federal_results_keep_the_ballot_box_districts_of_the_city(self):
        with mock.patch.object(packs, "fetch", return_value=self.federal):
            results = packs.btw25("Kiel,", "wbz")
        self.assertEqual(set(results), {"11", "15", "12"})
        self.assertEqual((results["11"].valid, results["11"].parties["Die Linke"]), (590, 120))

    def test_districts_sharing_a_polling_station_make_one_zone(self):
        features = [
            {"Wahlbezirk": "011/015", "Wahllokal": "Forum", "_geometry": MultiPolygon(square(0, 0), srid=4326)},
            {"Wahlbezirk": "012", "Wahllokal": "vhs", "_geometry": MultiPolygon(square(1, 0), srid=4326)},
            {"Wahlbezirk": "012", "Wahllokal": "vhs", "_geometry": MultiPolygon(square(1, 1), srid=4326)},
        ]
        with mock.patch.object(packs, "fetch", return_value=self.federal), \
                mock.patch.object(packs, "_layer", return_value=features):
            result = packs.run("kiel_btw25")
        by_code = {r.code: r for r in result.rows}
        self.assertEqual(set(by_code), {"011/015", "012"})
        self.assertEqual(by_code["011/015"].valid, 590 + 290)
        self.assertEqual(by_code["011/015"].parties["Die Linke"], 130)
        self.assertEqual(len(by_code["012"].geometry), 2)  # two pieces merged
        self.assertEqual(result.settings.reference_party_columns, ["Die Linke"])
        self.assertTrue(result.social_from_rent)

        ds.save_districts(self.organization, result.rows, result.election, result.settings)
        self.assertEqual(packs.social_from_rent(self.organization), 0)  # no census loaded in tests
        best = District.objects.filter(organization=self.organization).order_by("-score").first()
        self.assertEqual(best.code, "011/015")  # 130/880 Linke against 20/400
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.social_label, "Loyer net moyen (Zensus 2022)")
        self.assertFalse(self.organization.social_higher_is_poorer)

    def test_a_changed_source_is_reported(self):
        features = [{"Wahlbezirk": "077", "_geometry": MultiPolygon(square(0, 0), srid=4326)}]
        with mock.patch.object(packs, "fetch", return_value=self.federal), \
                mock.patch.object(packs, "_layer", return_value=features), \
                self.assertRaisesMessage(ds.DistrictImportError, "ne correspondent plus"):
            packs.run("kiel_btw25")

    def test_district_numbers_written_differently(self):
        self.assertEqual({packs.key("006-11"), packs.key("00611"), packs.key(611)}, {"611"})
        self.assertEqual(packs.key("B151"), "B151")

    def test_catalog_puts_the_city_of_the_organization_first(self):
        catalog = packs.catalog(self.organization)
        self.assertEqual((catalog[0]["key"], catalog[0]["recommended"]), ("kiel_btw25", True))
        self.assertEqual(sum(p["recommended"] for p in catalog), 1)
        self.assertEqual(len(catalog), 19)
        self.assertIsNone(packs.nearest(None, None))

    def test_import_api(self):
        from rest_framework.test import APIClient

        from accounts.models import Role, User

        manager = User.objects.create_user(email="resp@kiel.test", organization=self.organization, role=Role.MANAGER, is_approved=True)
        client = APIClient()
        client.force_authenticate(manager)
        self.assertEqual(client.get("/api/manage/districts/").json()["packs"][0]["key"], "kiel_btw25")
        self.assertEqual(client.post("/api/manage/districts/import/", {"pack": "atlantis"}, format="json").status_code, 400)
        with mock.patch.object(ds, "start_import") as start:
            response = client.post("/api/manage/districts/import/", {"pack": "kiel_btw25"}, format="json")
        self.assertEqual((response.status_code, response.json()["source"]), (202, "kiel_btw25"))
        start.assert_called_once()

    def test_multipolygon_kept(self):
        self.assertIsInstance(ds.as_multipolygon(square(0, 0)), MultiPolygon)


# --------------------------------------------------------------------------- voter list import (LEC)

from canvassing.models import Address, GeocodeCache  # noqa: E402
from canvassing.services import address_import  # noqa: E402

LEC_HEADER = ["Nom de naissance", "Nom d'usage", "Prénoms", "Date de naissance", "Lieu de naissance", "Pays de naissance",
              "Adresse de résidence", "Code postal", "Adresse électronique"]


def lec_file(people):
    """A consular list as exported by the consulate: title lines, then the table (fictitious people)."""
    rows = [[""] * 9, ["LISTE ELECTORALE CONSULAIRE"] + [""] * 8, [""] * 9, ["LEC de : BERLIN"] + [""] * 8,
            ["Date de l'édition : ", "08/05/2026 13:46"] + [""] * 7, ["Nombre d'inscrits : 3"] + [""] * 8, LEC_HEADER]
    rows += [[p[0], p[1], p[2], p[3], "Paris", "France", p[4], p[5], "x@example.org"] for p in people]
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, header=False, index=False)
    return buffer.getvalue()


PEOPLE = [
    ["DUPONT", "MARTIN", "Camille Léa", "01/02/1990", "Torstraße 12", "10115 Berlin"],
    ["DURAND", "", "Sacha", "03/04/1985", "Kastanienallee 7", "10435 Berlin"],
    ["LEROY", "LEROY", "Alex", "05/06/2001", "Sans numéro", "illisible"],
]


def fake_geocode(addresses, country_code, progress=None, warnings=None):
    rows = {}
    for key, addr in addresses.items():
        rows[key], _ = GeocodeCache.objects.get_or_create(  # the real one also reads the cache first
            query=key,
            defaults=dict(found=True, street=addr.street_name, zip_code=addr.zip_str, city=addr.city, lat=52.5 + len(rows) / 1000, lon=13.4),
        )
    return rows


@mock.patch("canvassing.services.geocoding.geocode_many", side_effect=fake_geocode)
class LecImportTests(TestCase):
    def setUp(self):
        self.voter_list = VoterList.objects.create(name="LEC test", country_code="DE")

    def test_read_lec(self, _):
        entries, report = address_import.read_file(lec_file(PEOPLE), "liste.xls", "DE")
        self.assertEqual(report.total, 3)
        self.assertEqual(report.invalid, 1)  # unreadable postcode
        first = entries[0]
        self.assertEqual((first.name, first.first_names, first.zip_code, first.city), ("MARTIN", "Camille Léa", "10115", "Berlin"))
        self.assertEqual(first.birth_year, 1990)
        self.assertEqual(entries[1].name, "DURAND")  # no usage name → birth name
        self.assertTrue(first.key.startswith("lec:"))
        self.assertNotIn("1990", first.key)  # date of birth only hashed

    def test_wrong_file(self, _):
        buffer = io.BytesIO()
        pd.DataFrame([["a", "b"], ["1", "2"]]).to_excel(buffer, header=False, index=False)
        with self.assertRaises(address_import.ImportFileError):
            address_import.read_file(buffer.getvalue(), "autre.xlsx", "DE")

    def test_import_then_reimport_with_a_move_and_a_departure(self, geocode):
        report = address_import.run_import(self.voter_list, lec_file(PEOPLE), "liste.xls")
        self.assertEqual((report.new, report.to_geocode), (2, 2))
        martin = Address.objects.get(voter_list=self.voter_list, name="MARTIN")
        self.assertEqual(martin.birth_year, 1990)
        self.assertNotIn("x@example.org", str(Address.objects.values().first()))

        moved = [PEOPLE[0][:4] + ["Kastanienallee 7", "10435 Berlin"]]  # Camille moved, Sacha left the list
        preview = address_import.preview(self.voter_list, lec_file(moved), "liste.xls")
        self.assertEqual((preview.new, preview.existing, preview.moved, preview.disabled), (0, 1, 1, 1))
        self.assertEqual(preview.to_geocode, 0)  # that address was already located once

        address_import.run_import(self.voter_list, lec_file(moved), "liste.xls")
        martin.refresh_from_db()
        self.assertEqual(martin.zip_code, "10435")
        self.assertIsNotNone(Address.all_objects.get(name="DURAND").disabled_at)

    def test_not_geocoded_people_are_left_out(self, geocode):
        geocode.side_effect = lambda addresses, *a, **k: {k: GeocodeCache(query=k, found=False) for k in addresses}
        report = address_import.run_import(self.voter_list, lec_file(PEOPLE[:1]), "liste.xls")
        self.assertEqual((report.new, report.not_geocoded), (0, 1))
        self.assertFalse(Address.objects.filter(voter_list=self.voter_list).exists())


class DistrictInfoTests(TestCase):
    """Progress of a district (what is left to do) and age pyramid of the French voters inside."""

    def setUp(self):
        from django.contrib.gis.geos import Point

        from accounts.models import User
        from canvassing.models import Address, Election, SocialArea, Status, Visit, VisitResult

        self.voter_list = VoterList.objects.create(name="LEC info")
        self.organization = Organization.objects.create(code="info", name="Info", voter_list=self.voter_list)
        self.district = District.objects.create(
            organization=self.organization, code="1", name="Nord", geometry=MultiPolygon(square(0, 0), srid=4326)
        )
        election = Election.current() or Election.objects.create(name="Élection test", is_current=True)
        old = Election.objects.create(name="Ancienne élection")
        Election.objects.filter(pk=old.pk).update(created_at="2020-01-01T00:00:00Z")
        self.election, self.old = election, old
        user = User.objects.create_user(email="v@demo.test", organization=self.organization, is_approved=True)
        year = __import__("datetime").date.today().year

        def person(name, status=Status.TO_VISIT, age=None, x=0.005):
            return Address.objects.create(
                voter_list=self.voter_list, name=name, address="1 rue", zip_code="10115", city="Berlin",
                location=Point(x, 0.005, srid=4326), status=status, birth_year=year - age if age else None,
            )

        person("JAMAIS", age=20)
        leaflet = person("BOITE", age=30)
        Visit.objects.create(address=leaflet, user=user, result=VisitResult.ADDRESS_TO_RETRY, absent_detail="leaflet", election=election)
        closed = person("FERMEE", age=30)
        Visit.objects.create(address=closed, user=user, result=VisitResult.ADDRESS_TO_RETRY, absent_detail="mailbox_inaccessible", election=election)
        before = person("AVANT", age=80)  # left a leaflet during a past election only: not leafleted for this one
        Visit.objects.create(address=before, user=user, result=VisitResult.ADDRESS_TO_RETRY, absent_detail="leaflet", election=old)
        person("EN_TOURNEE", Status.PLANNED, age=50)
        promise = person("PROMESSE", Status.COMMITMENT_TO_VOTE, age=17)
        Visit.objects.create(address=promise, user=user, result=VisitResult.COMMITMENT_TO_VOTE, election=election)
        refusal = person("REFUS", Status.DO_NOT_CONTACT)  # during the old election: out of the later ones
        Visit.objects.create(address=refusal, user=user, result=VisitResult.DO_NOT_CONTACT, election=old)
        person("AILLEURS", x=5)  # outside the district

        SocialArea.objects.create(source="t", code="a", name="A", geometry=MultiPolygon(square(0, 0, 0.005), srid=4326), low_income=0.3)
        SocialArea.objects.create(source="t", code="b", name="B", geometry=MultiPolygon(square(0.005, 0, 0.005), srid=4326), low_income=0.1)

    def test_progress_of_the_current_election(self):
        p = ds.progress(self.organization.id)[self.district.id]
        self.assertEqual(
            p,
            {"total": 6, "to_visit": 4, "remaining": 5, "not_leafleted": 4, "leafleted": 1, "done": 1, "done_pct": 16.7},
        )

    def test_progress_of_an_old_election(self):
        p = ds.progress(self.organization.id, election=self.old)[self.district.id]
        self.assertEqual((p["total"], p["done"], p["leafleted"], p["done_pct"]), (7, 1, 1, 14.3))

    def test_a_new_election_starts_at_zero(self):
        from canvassing.models import Election

        new = Election.objects.create(name="Nouvelle élection")
        p = ds.progress(self.organization.id, election=new)[self.district.id]
        # The refusal of the old election stays out; the promise of the previous one must be asked again.
        self.assertEqual((p["total"], p["done"], p["leafleted"], p["done_pct"]), (6, 0, 0, 0))

    def test_age_pyramid(self):
        ages = ds.age_pyramid(self.district)
        counts = {g["label"]: g["count"] for g in ages["groups"]}
        self.assertEqual(counts["18–24"], 2)  # 20 years old, and 17 counted with the youngest
        self.assertEqual(counts["25–34"], 2)
        self.assertEqual(counts["45–54"], 1)
        self.assertEqual(counts["75+"], 1)
        self.assertEqual(ages["unknown"], 1)

    def test_age_criterion_is_the_lfi_vote_expected_from_the_ages(self):
        stats = scoring.french_stats(self.organization.id)[self.district.id]
        # 20 and 17 → 41 %, two 30 → 30 %, 50 → 28 %, 80 → 19 %; the one without birth year is left out.
        self.assertAlmostEqual(stats.age_lfi_vote, (0.41 * 2 + 0.30 * 2 + 0.28 + 0.19) / 6)
        scoring.rescore_organization(self.organization)
        self.district.refresh_from_db()
        self.assertAlmostEqual(self.district.score_parts["age"]["value"], stats.age_lfi_vote)

    def test_low_income_without_census_uses_overlapping_area(self):
        self.assertEqual(ds.add_social(self.organization), 1)
        self.district.refresh_from_db()
        # Only the lower-left quarter of each area overlaps the district... both equally: mean of 0.3 and 0.1.
        self.assertAlmostEqual(self.district.social_value, 0.2, places=3)

    def test_own_social_areas_replace_the_shared_ones(self):
        from canvassing.models import SocialArea

        SocialArea.objects.create(
            organization=self.organization, source="ai:1", code="x", name="X",
            geometry=MultiPolygon(square(0, 0, 0.01), srid=4326), low_income=0.9,
        )
        ds.add_social(self.organization)
        self.district.refresh_from_db()
        self.assertAlmostEqual(self.district.social_value, 0.9, places=3)


class ActiveTourTests(TestCase):
    def test_preparing_a_tour_while_one_is_active_returns_its_id(self):
        from django.contrib.gis.geos import Point
        from django.test import Client

        from accounts.models import User
        from canvassing.models import Tour

        organization = Organization.objects.create(code="tours", name="Tours")
        user = User.objects.create_user(email="m@demo.test", organization=organization, is_approved=True)
        tour = Tour.objects.create(user=user, organization=organization, kind=Tour.Kind.FREE, status=Tour.TourStatus.ACTIVE, start_point=Point(13.4, 52.5))
        client = Client()
        client.force_login(user)
        response = client.post(
            "/api/tours/",
            {"kind": "free", "start": {"lat": 52.5, "lon": 13.4}, "end": {"lat": 52.51, "lon": 13.41}, "radius_km": 0.2},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "active_tour")
        self.assertEqual(response.json()["tour_id"], tour.id)


# --------------------------------------------------------------------------- elections & Telegram link

from canvassing.models import Election, Status, Visit  # noqa: E402
from canvassing.services import elections as election_service  # noqa: E402


class ElectionTelegramTests(TestCase):
    def setUp(self):
        from django.contrib.gis.geos import Point

        voter_list = VoterList.objects.create(name="LEC Berlin test")
        self.berlin = Organization.objects.create(code="berlin-insoumise", name="Berlin Insoumise", city="Berlin", voter_list=voter_list)
        self.election, _ = Election.objects.get_or_create(name="Élection consulaire 2026")
        Election.objects.update(is_current=False)
        Election.objects.filter(pk=self.election.pk).update(is_current=True)
        common = {"voter_list": voter_list, "zip_code": "10115", "city": "Berlin", "location": Point(13.4, 52.5)}
        self.martin = Address.objects.create(name="MARTIN", first_names="Camille", address="Torstraße 12", status=Status.COMMITMENT_TO_VOTE, **common)
        self.leroy = Address.objects.create(name="LEROY", first_names="Alex", address="Praterstraße 1", status=Status.DO_NOT_CONTACT, **common)
        # A visit made with the old Telegram bot: only the Telegram id of who made it is known.
        Visit.objects.create(address=self.martin, result="commitment_to_vote", election=self.election, telegram_user_id=123)

    def test_linking_telegram_gives_the_visits(self):
        import hashlib
        import hmac
        import time

        from django.test import Client, override_settings

        from accounts.models import User

        token = "4242:secret"
        user = User.objects.create_user(email="t@demo.test", organization=self.berlin, is_approved=True)
        client = Client()
        client.force_login(user)

        def signed(telegram_id, auth_date=None):
            data = {"id": telegram_id, "first_name": "Camille", "auth_date": int(auth_date or time.time())}
            check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
            data["hash"] = hmac.new(hashlib.sha256(token.encode()).digest(), check.encode(), hashlib.sha256).hexdigest()
            return data

        with override_settings(TELEGRAM_BOT_TOKEN=token):
            forged = {**signed(123), "id": 124}
            self.assertEqual(client.post("/api/auth/me/telegram/", forged, content_type="application/json").status_code, 400)
            old = signed(123, auth_date=time.time() - 2 * 24 * 3600)
            self.assertEqual(client.post("/api/auth/me/telegram/", old, content_type="application/json").status_code, 400)

            response = client.post("/api/auth/me/telegram/", signed(123), content_type="application/json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual((response.json()["telegram_id"], response.json()["linked_visits"]), (123, 1))
            self.assertEqual(Visit.objects.get(address=self.martin).user, user)
            # Once linked, no second link; and nobody else can take that Telegram account.
            self.assertEqual(client.post("/api/auth/me/telegram/", signed(124), content_type="application/json").status_code, 409)
            other = User.objects.create_user(email="o@demo.test", organization=self.berlin, is_approved=True)
            client.force_login(other)
            self.assertEqual(client.post("/api/auth/me/telegram/", signed(123), content_type="application/json").status_code, 409)

    def test_new_election_starts_over_but_keeps_do_not_contact(self):
        presidential = Election.objects.create(name="Élection présidentielle 2027")
        self.assertEqual(election_service.set_current(presidential), 1)  # the promise of MARTIN
        self.assertEqual(Address.objects.get(pk=self.martin.pk).status, Status.TO_VISIT)
        self.assertEqual(Address.objects.get(pk=self.leroy.pk).status, Status.DO_NOT_CONTACT)
        self.assertEqual(Election.objects.filter(is_current=True).get(), presidential)
        self.assertEqual(election_service.phrase(presidential), "pour l'élection présidentielle 2027")

    def test_do_not_contact_and_not_found_from_a_past_election_stay_out_of_the_tours(self):
        from django.contrib.gis.geos import Point

        common = {"voter_list": self.martin.voter_list, "zip_code": "10115", "city": "Berlin", "location": Point(13.4, 52.5)}
        # Statuses out of step with their history (e.g. an old import): the last visit decides.
        hostile = Address.objects.create(name="A", address="Rue 1", status=Status.COMMITMENT_TO_VOTE, **common)
        Visit.objects.create(address=hostile, result="do_not_contact", election=self.election)
        missing = Address.objects.create(name="B", address="Rue 2", status=Status.TO_VISIT, **common)
        Visit.objects.create(address=missing, result="address_failure", election=self.election)

        election_service.set_current(Election.objects.create(name="Élection européenne"))
        hostile.refresh_from_db()
        missing.refresh_from_db()
        self.assertEqual((hostile.status, missing.status), (Status.DO_NOT_CONTACT, Status.FAILURE))
        self.assertEqual(Address.objects.get(pk=self.martin.pk).status, Status.TO_VISIT)  # a promise: to visit again


class SiteAdminTests(TestCase):
    def test_only_site_admins(self):
        from django.test import Client

        from accounts.models import Role, User

        organization = Organization.objects.create(code="o", name="O")
        manager = User.objects.create_user(email="r@demo.test", organization=organization, role=Role.MANAGER, is_approved=True)
        admin = User.objects.create_user(email="a@demo.test", role=Role.ADMIN, is_approved=True)
        client = Client()
        client.force_login(manager)
        self.assertEqual(client.get("/api/site/elections/").status_code, 403)
        client.force_login(admin)
        created = client.post("/api/site/elections/", {"name": "Élection présidentielle 2027"}, content_type="application/json")
        self.assertEqual(created.status_code, 201)
        response = client.post(f"/api/site/elections/{created.json()['id']}/activate/")
        self.assertTrue(response.json()["is_current"])
        names = [e["name"] for e in client.get("/api/site/elections/").json()["elections"] if e["is_current"]]
        self.assertEqual(names, ["Élection présidentielle 2027"])


from canvassing.addressutils import AddressNotGeolocated  # noqa: E402


class FuzzyGeocodingTests(SimpleTestCase):
    """Hand-typed addresses of the electoral lists: cleaning, spelling variants, typo correction."""

    def test_cleaning(self):
        from canvassing.services.geocoding import clean_city, clean_number, clean_street, street_variants

        self.assertEqual(clean_street("GÖRREstr."), "Görrestraße")
        self.assertEqual(clean_street("Theodor-Storm-str."), "Theodor-Storm-Straße")
        self.assertEqual(clean_street("Argentinische Alle"), "Argentinische Allee")
        self.assertEqual(clean_street("BGM.-Kürten-str."), "Bürgermeister-Kürten-Straße")
        self.assertEqual(clean_street("Prahmstr.,"), "Prahmstraße")
        self.assertEqual(clean_number("172 a"), "172a")
        self.assertEqual(clean_number("2F-K"), "2F")
        self.assertEqual(clean_city("CHEMNITZ OT WITTGENSDORF"), "Chemnitz")
        self.assertEqual(clean_city("PETERSAHGEN / EGGENSDORF"), "Petersahgen")
        self.assertIn("Bayerische Straße", street_variants("Bayerischestraße"))
        self.assertIn("Freiberger Straße", street_variants("Freibergstraße"))
        self.assertIn("Rudolf-Breitscheid-Straße", street_variants("Rudolf Breitscheid Straße"))
        # Flat after the house number (Austria: "Top", "Stiege"…; Germany: "DG", "Whg").
        self.assertEqual(clean_number("4 b top 39"), "4b")
        self.assertEqual(clean_number("3 top 11"), "3")
        self.assertEqual(clean_number("3 DG"), "3")
        self.assertEqual(clean_number("4 Whg 313"), "4")
        self.assertEqual(clean_number("1 OT Hoppenrade"), "1")
        self.assertEqual(clean_street("Hauptstrabe"), "Hauptstraße")
        self.assertEqual(clean_street("c/o Manuela Jannarelli Westerfeldstr."), "Westerfeldstraße")
        self.assertEqual(clean_street("Schachendorf Nr ."), "Schachendorf")
        self.assertIn("Schönhauser Allee", street_variants("Schönhauserallee"))
        self.assertIn("Otto-Bauer-Gasse", street_variants("Otto-Bauergasse"))
        self.assertIn("Franz-Emrich-Gasse", street_variants("Franz Emrichgasse"))
        self.assertEqual(street_variants("Panoramaweg"), ["Panoramaweg"])
        self.assertIn("Lissabonallee", street_variants("Lissabon Allee"))
        self.assertEqual(clean_street("Landstr.r Hauptstr."), "Landstraßer Hauptstraße")

    def test_village_address_without_street(self):
        """Austria: "Harbach 86" is a house of the village, with no street name."""
        from canvassing.services import geocoding

        class Location:
            latitude, longitude = 47.17, 13.1
            raw = {"address": {"hamlet": "Harbach", "house_number": "86", "postcode": "5630", "village": "Bad Hofgastein"}}

        def fake(query, **kwargs):  # only the free-text search finds it
            return Location() if isinstance(query, str) else None

        addr = AddressNotGeolocated("", "", "Harbach", "86", "5630", "Bad Hofgastein")
        location = geocoding.geocode_direct(addr, "AT", fake)
        self.assertEqual(geocoding.location_to_fields(addr, location)["address"], "Harbach 86")

        wrong_number = AddressNotGeolocated("", "", "Harbach", "12", "5630", "Bad Hofgastein")
        self.assertIsNone(geocoding.geocode_direct(wrong_number, "AT", fake))

    def test_same_street(self):
        from canvassing.services.geocoding import same_street

        self.assertTrue(same_street("Hauptstraße", "Haupstr."))
        self.assertTrue(same_street("Voßstraße", "VOSSstr."))
        self.assertTrue(same_street("Lotzestraße - Lotzowa", "Lotzestr."))
        self.assertFalse(same_street("Marchstraße", "Trasoltstr."))
        self.assertFalse(same_street("Im Ring", "Im Loog"))

    def test_number_written_first(self):
        from canvassing.services.geocoding import number_first

        fixed = number_first(AddressNotGeolocated("", "", "", "46 Alt-Moabit", "10559", "Berlin"))
        self.assertEqual((fixed.street_name, fixed.street_number), ("Alt-Moabit", "46"))

    def test_known_streets_correct_typos_within_the_postcode(self):
        from canvassing.services.geocoding import KnownStreets

        known = KnownStreets([("Thrasoltstraße", "10585", "Berlin"), ("Marchstraße", "10587", "Berlin")])
        self.assertEqual(known.correct("Trasoltstraße", "10585", "Berlin"), ["Thrasoltstraße"])
        self.assertEqual(known.correct("Fantasiestraße", "10585", "Berlin"), [])

    def test_cascade_uses_the_corrected_street(self):
        from canvassing.services import geocoding

        class Location:
            def __init__(self, road, number):
                self.latitude, self.longitude = 52.5, 13.4
                self.raw = {"address": {"road": road, "house_number": number, "postcode": "12524", "city": "Berlin"}}

        def fake(query, **kwargs):  # only the right spelling exists
            return Location("Pfarrwöhrde", "17") if isinstance(query, dict) and query["street"] == "Pfarrwöhrde 17" else None

        addr = AddressNotGeolocated("", "", "Pfarrwörde", "17", "12524", "BERLIN")
        self.assertIsNone(geocoding.geocode_direct(addr, "DE", fake))
        known = geocoding.KnownStreets([("Pfarrwöhrde", "12524", "Berlin")])
        location = geocoding.geocode_corrected(addr, "DE", fake, known)
        self.assertEqual(geocoding.location_to_fields(addr, location)["address"], "Pfarrwöhrde 17")


def arcgis_answer(street="Pfarrwöhrde", number="17", postcode="12524", addr_type="PointAddress", found=True):
    """A findAddressCandidates response (shape of geocode.arcgis.com/.../GeocodeServer/findAddressCandidates)."""
    attributes = {"Addr_type": addr_type, "AddNum": number, "StAddr": f"{street} {number}", "StName": street,
                  "Postal": postcode, "City": "Berlin"}
    candidate = {"address": f"{street} {number}, {postcode} Berlin", "score": 98,
                 "location": {"x": 13.55, "y": 52.43}, "attributes": attributes}
    return {"candidates": [candidate] if found else []}


class FakeArcGIS:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        return mock.Mock(json=lambda: self.answer)


class ArcGISGeocodingTests(TestCase):
    """ArcGIS is the last resort: only for addresses OpenStreetMap could not locate, each one sent once."""

    addr = AddressNotGeolocated("", "", "Pfarrwörde", "17", "12524", "BERLIN")

    def test_only_the_right_house_is_kept(self):
        from canvassing.services import geocoding

        hit = geocoding.arcgis_geocode(self.addr, "DE", FakeArcGIS(arcgis_answer()))
        fields = geocoding.location_to_fields(self.addr, hit)
        self.assertEqual((fields["address"], fields["lat"], fields["lon"]), ("Pfarrwöhrde 17", 52.43, 13.55))
        hit = geocoding.arcgis_geocode(self.addr, "DE", FakeArcGIS(arcgis_answer(postcode="12525")))  # postcode typo
        self.assertEqual(geocoding.location_to_fields(self.addr, hit)["zip_code"], "12525")
        for answer in (
            arcgis_answer(number="19"),  # another house
            arcgis_answer(postcode="80331"),  # another town
            arcgis_answer(street="Emichgasse", postcode="12525"),  # another street in the next postcode
            arcgis_answer(addr_type="StreetName"),  # the street only
            arcgis_answer(found=False),
        ):
            self.assertIsNone(geocoding.arcgis_geocode(self.addr, "DE", FakeArcGIS(answer)))
        with self.assertRaises(geocoding.ArcGISUnavailable):
            geocoding.arcgis_geocode(self.addr, "DE", FakeArcGIS({"error": {"code": 498, "message": "Invalid token."}}))

    @mock.patch("canvassing.services.geocoding.geocode_corrected", return_value=None)
    @mock.patch("canvassing.services.geocoding.geocode_direct", return_value=None)
    def test_sent_once_and_never_for_located_addresses(self, *_):
        from canvassing.services import geocoding

        located = AddressNotGeolocated("", "", "Torstraße", "12", "10115", "Berlin")
        located_key = geocoding.cache_key(located, "DE")
        GeocodeCache.objects.create(query=located_key, found=True, street="Torstraße", zip_code="10115", city="Berlin", lat=52.5, lon=13.4)
        key = geocoding.cache_key(self.addr, "DE")

        arcgis = FakeArcGIS(arcgis_answer())
        with mock.patch("canvassing.services.geocoding.arcgis_session", return_value=arcgis):
            rows = geocoding.geocode_many({key: self.addr, located_key: located}, "DE")
        self.assertEqual(len(arcgis.calls), 1)
        self.assertEqual(arcgis.calls[0]["SingleLine"], "Pfarrwörde 17, 12524 Berlin")
        self.assertEqual((rows[key].found, rows[key].street), (True, "Pfarrwöhrde"))

        # Not found by ArcGIS either: cached as tried, never sent again.
        other = AddressNotGeolocated("", "", "Nirgendwo", "3", "12524", "Berlin")
        other_key = geocoding.cache_key(other, "DE")
        for expected_calls in (1, 0):
            arcgis = FakeArcGIS(arcgis_answer(found=False))
            with mock.patch("canvassing.services.geocoding.arcgis_session", return_value=arcgis):
                rows = geocoding.geocode_many({other_key: other}, "DE")
            self.assertEqual((len(arcgis.calls), rows[other_key].found), (expected_calls, False))
        self.assertIsNotNone(GeocodeCache.objects.get(query=other_key).arcgis_tried_at)

    @mock.patch("canvassing.services.geocoding.geocode_corrected", return_value=None)
    @mock.patch("canvassing.services.geocoding.geocode_direct", return_value=None)
    def test_outage(self, *_):
        from canvassing.services import geocoding

        key = geocoding.cache_key(self.addr, "DE")
        arcgis = FakeArcGIS({"error": {"code": 429, "message": "Too many requests"}})
        warnings = []
        with mock.patch("canvassing.services.geocoding.arcgis_session", return_value=arcgis):
            geocoding.geocode_many({key: self.addr}, "DE", warnings=warnings)
        self.assertIn("Too many requests", warnings[0])  # shown in the import report
        self.assertIsNone(GeocodeCache.objects.get(query=key).arcgis_tried_at)  # retried at the next import


class SuspendedMemberTests(TestCase):
    def test_a_suspended_member_is_not_a_sign_up_to_validate(self):
        from django.test import Client

        from accounts.models import Role, User

        organization = Organization.objects.create(code="o", name="O")
        manager = User.objects.create_user(email="r@demo.test", organization=organization, role=Role.MANAGER, is_approved=True)
        member = User.objects.create_user(email="m@demo.test", organization=organization, is_approved=True)
        client = Client()
        client.force_login(manager)
        url = f"/api/manage/members/{member.pk}/"
        listed = lambda status: [m["id"] for m in client.get("/api/manage/members/", {"status": status}).json()]  # noqa: E731

        self.assertEqual(client.patch(url, {"is_approved": False}, content_type="application/json").status_code, 200)
        self.assertNotIn(member.pk, listed("pending"))
        self.assertIn(member.pk, listed("members"))
        self.assertEqual(client.delete(url).status_code, 409)  # suspended, not refused

        reactivated = client.patch(url, {"is_approved": True}, content_type="application/json").json()
        self.assertEqual((reactivated["is_approved"], reactivated["suspended_at"]), (True, None))


class ClearResultTests(TestCase):
    def test_tapping_the_selected_feedback_again_removes_it(self):
        from django.contrib.gis.geos import Point
        from django.test import Client

        from accounts.models import User
        from canvassing.models import Tour, TourStop

        voter_list = VoterList.objects.create(name="LEC clear")
        organization = Organization.objects.create(code="clear", name="Clear", voter_list=voter_list)
        user = User.objects.create_user(email="m@demo.test", organization=organization, is_approved=True)
        address = Address.objects.create(
            voter_list=voter_list, name="X", address="Rue 1", zip_code="10115", city="Berlin",
            location=Point(13.4, 52.5), status=Status.PLANNED, visit_planned_by=user,
        )
        tour = Tour.objects.create(user=user, organization=organization, kind=Tour.Kind.FREE, status=Tour.TourStatus.ACTIVE, start_point=Point(13.4, 52.5))
        stop = TourStop.objects.create(tour=tour, address=address, position=0)
        client = Client()
        client.force_login(user)
        url = f"/api/tours/{tour.id}/results/"
        client.post(url, {"stop_ids": [stop.id], "result": "commitment_to_vote"}, content_type="application/json")
        self.assertEqual(Visit.objects.filter(stop=stop).count(), 1)

        response = client.delete(f"{url}?stop_ids={stop.id}")
        self.assertEqual(response.status_code, 200)
        stop.refresh_from_db()
        address.refresh_from_db()
        self.assertEqual((stop.result, stop.visited_at, address.status), ("", None, Status.PLANNED))
        self.assertFalse(Visit.objects.filter(stop=stop).exists())

        # "Peu intéressée": met, done for this election, back to visit at the next one; not a success.
        client.post(url, {"stop_ids": [stop.id], "result": "not_interested"}, content_type="application/json")
        address.refresh_from_db()
        self.assertEqual(address.status, Status.NOT_INTERESTED)
        from canvassing.services.tours import tour_summary

        summary = tour_summary(tour)
        self.assertEqual((summary["not_interested"], summary["total_success"]), (1, 0))
        self.assertEqual(election_service.addresses_to_reset().filter(pk=address.pk).count(), 1)


class BrevoBackendTests(SimpleTestCase):
    def test_email_is_posted_to_brevo(self):
        from django.core.mail import EmailMultiAlternatives
        from django.test import override_settings

        message = EmailMultiAlternatives("Sujet", "Texte", "Porte-à-porte <no-reply@exemple.org>", ["a@exemple.org"])
        message.attach_alternative("<p>HTML</p>", "text/html")
        with override_settings(EMAIL_BACKEND="accounts.brevo.BrevoEmailBackend", BREVO_API_KEY="k"), mock.patch(
            "accounts.brevo.requests.post", return_value=mock.Mock(status_code=201)
        ) as post:
            self.assertEqual(message.send(), 1)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["sender"], {"email": "no-reply@exemple.org", "name": "Porte-à-porte"})
        self.assertEqual((payload["to"], payload["htmlContent"]), ([{"email": "a@exemple.org"}], "<p>HTML</p>"))
        self.assertEqual(post.call_args.kwargs["headers"]["api-key"], "k")


class SharedVoterListTests(TestCase):
    """Two organizations on one voter list: shared addresses, each one sees those around its city only;
    only the site admins manage the lists."""

    def setUp(self):
        from django.contrib.gis.geos import Point

        from accounts.models import Role, User

        self.voter_list = VoterList.objects.create(name="LEC Berlin", country_code="DE")
        self.berlin = Organization.objects.create(
            code="berlin", name="Berlin", city="Berlin", city_lat=52.52, city_lon=13.40, voter_list=self.voter_list
        )
        self.leipzig = Organization.objects.create(
            code="leipzig", name="Leipzig", city="Leipzig", city_lat=51.34, city_lon=12.37, voter_list=self.voter_list
        )
        for name, (lat, lon) in {"BERLINOIS": (52.53, 13.41), "LEIPZIGOIS": (51.35, 12.38)}.items():
            Address.objects.create(
                voter_list=self.voter_list, name=name, address="Rue 1", zip_code="10115", city="X", location=Point(lon, lat)
            )
        self.manager = User.objects.create_user(
            email="resp@demo.test", organization=self.leipzig, role=Role.MANAGER, is_approved=True
        )
        self.admin = User.objects.create_user(email="admin@demo.test", role=Role.ADMIN, is_approved=True)

    def test_each_organization_sees_the_addresses_around_its_city(self):
        from canvassing.services.scope import organization_addresses

        self.assertEqual(list(organization_addresses(self.berlin).values_list("name", flat=True)), ["BERLINOIS"])
        self.assertEqual(list(organization_addresses(self.leipzig).values_list("name", flat=True)), ["LEIPZIGOIS"])
        self.leipzig.radius_km = 200
        self.assertEqual(organization_addresses(self.leipzig).count(), 2)

    def test_organization_created_with_its_logo(self):
        import io

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        from rest_framework.test import APIClient

        buffer = io.BytesIO()
        Image.new("RGB", (40, 40), "red").save(buffer, "PNG")
        client = APIClient()
        client.force_authenticate(self.admin)
        response = client.post(
            "/api/manage/organizations/",
            {
                "name": "Dresde", "city": "Dresden", "city_lat": "51.05", "city_lon": "13.74", "country_code": "DE",
                "voter_list": self.voter_list.id, "radius_km": 20,
                "logo": SimpleUploadedFile("logo.png", buffer.getvalue(), content_type="image/png"),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(response.json()["logo_url"])
        self.assertEqual(Organization.objects.get(code="dresde").logo_content_type, "image/webp")

    def test_only_site_admins_manage_voter_lists(self):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(self.manager)
        self.assertEqual(client.get("/api/manage/voter-lists/").status_code, 403)
        self.assertEqual(client.get(f"/api/manage/voter-lists/{self.voter_list.id}/addresses/import/").status_code, 403)
        other = VoterList.objects.create(name="LEC Munich")
        response = client.patch("/api/manage/organizations/leipzig/", {"voter_list": other.id}, format="json")
        self.assertIn(response.status_code, (403, 405))

        client.force_authenticate(self.admin)
        lists = client.get("/api/manage/voter-lists/").json()
        berlin = next(v for v in lists if v["name"] == "LEC Berlin")
        self.assertEqual((berlin["n_active"], {o["code"] for o in berlin["organizations"]}), (2, {"berlin", "leipzig"}))
        # Name, city and LEC are fixed at creation: nobody can change them afterwards.
        response = client.patch("/api/manage/organizations/leipzig/", {"voter_list": other.id}, format="json")
        self.assertEqual(response.status_code, 405)
        # A list with addresses cannot be deleted (their visits would go with them).
        self.assertEqual(client.delete(f"/api/manage/voter-lists/{self.voter_list.id}/").status_code, 400)
        self.assertEqual(client.delete(f"/api/manage/voter-lists/{other.id}/").status_code, 400 if other.addresses.exists() else 204)


class LeaderboardElectionTests(TestCase):
    def test_only_the_doors_of_the_current_election_count(self):
        from django.contrib.gis.geos import Point
        from django.test import Client

        from accounts.models import User

        Election.objects.update(is_current=False)
        current = Election.objects.create(name="Élection en cours", is_current=True)
        past = Election.objects.create(name="Élection passée")
        voter_list = VoterList.objects.create(name="LEC classement")
        organization = Organization.objects.create(code="rank", name="Rank", voter_list=voter_list)
        alice = User.objects.create_user(email="a@demo.test", first_name="Alice", organization=organization, is_approved=True)
        bob = User.objects.create_user(email="b@demo.test", first_name="Bob", organization=organization, is_approved=True)
        address = Address.objects.create(
            voter_list=voter_list, name="X", address="Rue 1", zip_code="10115", city="Berlin", location=Point(13.4, 52.5)
        )
        # Bob knocked lots of doors in the past election, Alice one in the current one.
        for _ in range(3):
            Visit.objects.create(address=address, user=bob, result="failure", election=past)
        Visit.objects.create(address=address, user=alice, result="failure", election=current)

        client = Client()
        client.force_login(alice)
        group = client.get("/api/stats/leaderboard/", {"scope": "group"}).json()
        self.assertEqual(group["election"], "Élection en cours")
        doors = {r["id"]: (r["rank"], r["doors"]) for r in group["rows"]}
        self.assertEqual(doors, {alice.id: (1, 1), bob.id: (2, 0)})

        orgs = client.get("/api/stats/leaderboard/", {"scope": "organizations"}).json()
        self.assertEqual(next(r["doors"] for r in orgs["rows"] if r["id"] == organization.id), 1)



class SocialIndicatorUploadTests(TestCase):
    def setUp(self):
        from django.contrib.gis.geos import Point

        from accounts.models import Role, User

        self.organization = Organization.objects.create(code="o", name="O")
        self.manager = User.objects.create_user(email="r@demo.test", organization=self.organization, role=Role.MANAGER, is_approved=True)
        for code, x in (("01/001", 0), ("01/002", 1), ("99", 2)):
            square = Polygon.from_bbox((x, 0, x + 1, 1))
            square.srid = 4326
            District.objects.create(
                organization=self.organization, code=code, name=code, geometry=MultiPolygon(square, srid=4326),
                label_point=Point(x + 0.5, 0.5, srid=4326),
            )

    def feature(self, code, value, x):
        return {
            "type": "Feature",
            "properties": {"bureau_vote": code, "minima_sociaux_pct": value, "indicateur": "SGB II", "date_donnees": "2025"},
            "geometry": {"type": "Polygon", "coordinates": [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 1], [x, 0]]]},
        }

    def upload(self, features):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import Client

        client = Client()
        client.force_login(self.manager)
        data = json.dumps({"type": "FeatureCollection", "features": features}).encode()
        return client.post("/api/manage/districts/social/", {"file": SimpleUploadedFile("ville.geojson", data)})

    def test_values_by_number_then_by_outline(self):
        # "01001" is district "01/001"; "X" matches no number but its outline contains district "99".
        response = self.upload([self.feature("01001", 12.5, 0), self.feature("01002", 3, 1), self.feature("X", 7, 2)])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["n_with_social"], 3)
        values = dict(District.objects.filter(organization=self.organization).values_list("code", "social_value"))
        self.assertEqual(values, {"01/001": 0.125, "01/002": 0.03, "99": 0.07})
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.social_label, "Minima sociaux (% des habitants)")

        # Re-importing the pack recreates the districts: the uploaded values are applied again.
        from .services import social

        District.objects.filter(organization=self.organization).update(social_value=None)
        self.organization.social_label = "Loyer net moyen (Zensus 2022)"
        self.organization.save()
        self.assertEqual(social.apply_saved(self.organization), 3)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.social_label, "Minima sociaux (% des habitants)")

    def test_file_of_another_city_is_refused(self):
        response = self.upload([self.feature("01001", 12.5, 50), self.feature("01002", 3, 51)])
        self.assertEqual(response.status_code, 400)
        self.assertIn("pas le fichier de ta ville", response.json()["detail"])

    def test_missing_columns(self):
        response = self.upload([{"type": "Feature", "properties": {"x": 1}, "geometry": None}])
        self.assertEqual(response.status_code, 400)
        self.assertIn("minima_sociaux_pct", response.json()["detail"])
