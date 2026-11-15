import io
import json

import pandas as pd
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.test import SimpleTestCase, TestCase

from accounts.models import Organization

from .models import District
from .services import districts as ds
from .services import scoring


def square(x, y, size=0.01):
    return Polygon(((x, y), (x + size, y), (x + size, y + size), (x, y + size), (x, y)), srid=4326)


def feature(props, x, y):
    return {"type": "Feature", "properties": props, "geometry": json.loads(square(x, y).geojson)}


class ScoringTests(SimpleTestCase):
    def test_percentile_ranks_handle_ties(self):
        self.assertEqual(scoring.percentile_ranks({1: 10, 2: 20, 3: 20, 4: 30}), {1: 0, 2: 0.5, 3: 0.5, 4: 1})

    def test_score_is_weighted_mean_of_ranks_and_skips_missing_data(self):
        a = District(id=1, linke=10, valid=100, voters=50, eligible=100, rent_m2=None)
        b = District(id=2, linke=40, valid=100, voters=80, eligible=100, rent_m2=None)
        scoring.compute_scores([a, b], {"linke": 50, "abstention": 50, "young": 0, "density": 0, "low_rent": 30})
        # b: best Linke vote (rank 1) but least abstention (rank 0); rent is missing everywhere → ignored.
        self.assertEqual(a.score, 50)
        self.assertEqual(b.score, 50)
        scoring.compute_scores([a, b], {"linke": 100, "abstention": 0, "young": 0, "density": 0, "low_rent": 0})
        self.assertEqual((a.score, b.score), (0, 100))
        self.assertIsNone(a.score_parts["low_rent"]["rank"])

    def test_low_rent_is_better(self):
        a, b = District(id=1, rent_m2=6), District(id=2, rent_m2=12)
        scoring.compute_scores([a, b], {"low_rent": 10})
        self.assertGreater(a.score, b.score)

    def test_clean_weights(self):
        self.assertEqual(scoring.clean_weights({"linke": "150", "young": -3})["linke"], 100)
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
        self.assertEqual(by_code["01101"].linke, 100 + 50)
        self.assertEqual(by_code["01102"].linke, 50 + 150)
        self.assertEqual(by_code["01102"].voters, 100 + 300)
        self.assertEqual(sum(r.linke for r in rows), 100 + 50 + 200)


class CustomImportTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(code="test", name="Test")

    def files(self):
        geometry = json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    feature({"nr": "0001", "label": "Nord"}, 0, 0),
                    feature({"nr": "0002", "label": "Sud"}, 1, 0),
                    feature({"nr": "0002", "label": "Sud"}, 1, 1),  # same district, second piece
                    feature({"nr": "0003", "label": "Est"}, 2, 0),
                ],
            }
        ).encode()
        results = "Bezirk;Gültig;LINKE;SPD\n1;100;30;20\n2;200;20;100\n2;50;10;5\n9;10;1;1\n".encode()
        return geometry, results

    def test_inspect(self):
        geometry, results = self.files()
        info = ds.inspect_files(geometry, results, "res.csv")
        self.assertEqual(info["columns"], ["Bezirk", "Gültig", "LINKE", "SPD"])
        self.assertIn("nr", info["geometry_properties"])

    def test_rows_match_ids_merge_pieces_and_sum_lines(self):
        geometry, results = self.files()
        mapping = {"geo_id": "nr", "geo_name": "label", "res_id": "Bezirk", "linke": "LINKE", "valid": "Gültig", "parties": ["LINKE", "SPD"]}
        rows, report = ds.rows_from_custom(geometry, results, "res.csv", mapping)
        by_code = {r.code: r for r in rows}
        self.assertEqual(len(rows), 3)
        self.assertEqual(by_code["0002"].linke, 30)  # two result lines summed
        self.assertEqual(by_code["0002"].valid, 250)
        self.assertEqual(len(by_code["0002"].geometry), 2)  # two pieces merged
        self.assertEqual(by_code["0002"].parties, {"LINKE": 30, "SPD": 105})
        self.assertEqual(report["n_without_results"], 1)  # 0003
        self.assertEqual(report["n_results_without_district"], 1)  # 9

        result = ds.save_districts(self.organization, rows, "Test")
        self.assertEqual(result["n_districts"], 3)
        best = District.objects.filter(organization=self.organization).order_by("-score").first()
        self.assertEqual(best.code, "0001")  # 30 % Linke
        self.assertGreater(best.area_km2, 0)
        self.assertIsNotNone(best.label_point)

    def test_wrong_ids_are_reported(self):
        geometry, results = self.files()
        mapping = {"geo_id": "label", "res_id": "Bezirk", "linke": "LINKE", "valid": "Gültig"}
        with self.assertRaises(ds.DistrictImportError):
            ds.rows_from_custom(geometry, results, "res.csv", mapping)

    def test_multipolygon_kept(self):
        self.assertIsInstance(ds.as_multipolygon(square(0, 0)), MultiPolygon)


# --------------------------------------------------------------------------- voter list import (LEC)

from unittest import mock  # noqa: E402

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


def fake_geocode(addresses, country_code, progress=None):
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
        self.organization = Organization.objects.create(code="lec", name="LEC", country_code="DE")

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
        report = address_import.run_import(self.organization, lec_file(PEOPLE), "liste.xls")
        self.assertEqual((report.new, report.to_geocode), (2, 2))
        martin = Address.objects.get(organization=self.organization, name="MARTIN")
        self.assertEqual(martin.birth_year, 1990)
        self.assertNotIn("x@example.org", str(Address.objects.values().first()))

        moved = [PEOPLE[0][:4] + ["Kastanienallee 7", "10435 Berlin"]]  # Camille moved, Sacha left the list
        preview = address_import.preview(self.organization, lec_file(moved), "liste.xls")
        self.assertEqual((preview.new, preview.existing, preview.moved, preview.disabled), (0, 1, 1, 1))
        self.assertEqual(preview.to_geocode, 0)  # that address was already located once

        address_import.run_import(self.organization, lec_file(moved), "liste.xls")
        martin.refresh_from_db()
        self.assertEqual(martin.zip_code, "10435")
        self.assertIsNotNone(Address.all_objects.get(name="DURAND").disabled_at)

    def test_not_geocoded_people_are_left_out(self, geocode):
        geocode.side_effect = lambda addresses, *a, **k: {k: GeocodeCache(query=k, found=False) for k in addresses}
        report = address_import.run_import(self.organization, lec_file(PEOPLE[:1]), "liste.xls")
        self.assertEqual((report.new, report.not_geocoded), (0, 1))
        self.assertFalse(Address.objects.filter(organization=self.organization).exists())


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


# --------------------------------------------------------------------------- bot database import & elections

import tempfile  # noqa: E402

from django.core.management import call_command  # noqa: E402

from canvassing.models import Election, Status, Visit  # noqa: E402
from canvassing.services import elections as election_service  # noqa: E402

BOT_DUMP = """--
-- PostgreSQL database dump
--
COPY public.area (id, name, consulat, geometry, score, archived, note) FROM stdin;
\\.
COPY public.address (id, consulat, usage_name, first_name, address, zip_code, city, lat, lon, n_visits, status, visit_planned_at, visit_planned_by, family_name) FROM stdin;
1\tBERLIN\t\\N\tCamille\tTorstraße 12\t10115\tBerlin\t52.53\t13.40\t1\t4\t2026-05-10 18:30:00\t123\tMARTIN
2\tBERLIN\t\\N\tCamille\tTorstraße 12\t10115\tBerlin\t52.53\t13.40\t0\t\\N\t\\N\t\\N\tMARTIN
3\tBERLIN\tDURAND\tSacha\tKastanienallee 7\t10435\tBerlin\t52.54\t13.41\t2\t7\t2026-05-11 10:00:00\t124\tDUPUIS
4\tWIEN\t\\N\tAlex\tPraterstraße 1\t1020\tWien\t48.21\t16.38\t0\t\\N\t\\N\t\\N\tLEROY
\\.
"""


class BotImportTests(TestCase):
    def setUp(self):
        self.berlin = Organization.objects.create(code="berlin-insoumise", name="Berlin Insoumise", city="Berlin")
        self.file = tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False, encoding="utf-8")
        self.file.write(BOT_DUMP)
        self.file.close()

    def run_import(self, *args):
        out = io.StringIO()
        call_command("import_bot_db", self.file.name, *args, stdout=out)
        return out.getvalue()

    def test_import(self):
        output = self.run_import()
        self.assertIn("Nouvelles adresses : 3", output)
        self.assertIn("1 dans le fichier", output)
        self.assertIn("1 promesses de vote pour l'élection consulaire 2026", output)
        martin = Address.objects.get(organization=self.berlin, name="MARTIN")
        self.assertEqual(martin.status, Status.COMMITMENT_TO_VOTE)  # the duplicate with a visit was kept
        visit = Visit.objects.get(address=martin)
        self.assertEqual((visit.election.name, visit.created_at.day), ("Élection consulaire 2026", 10))
        durand = Address.objects.get(name="DURAND")
        self.assertEqual(durand.status, Status.TO_VISIT)  # absent → to visit again
        self.assertEqual(Visit.objects.get(address=durand).absent_detail, "leaflet")  # status 7
        vienna = Organization.objects.get(code="vienne-insoumise")  # created
        self.assertEqual((vienna.country_code, vienna.addresses.count()), ("AT", 1))

        again = self.run_import()  # nothing added twice
        self.assertIn("Nouvelles adresses : 0", again)
        self.assertEqual(Address.all_objects.count(), 3)
        self.assertEqual(Visit.objects.count(), 2)

    def test_dry_run_changes_nothing(self):
        self.assertIn("SIMULATION", self.run_import("--dry-run"))
        self.assertFalse(Address.all_objects.exists())
        self.assertFalse(Organization.objects.filter(code="vienne-insoumise").exists())

    def test_new_election_starts_over_but_keeps_do_not_contact(self):
        self.run_import()
        dnc = Address.objects.get(name="LEROY")
        dnc.status = Status.DO_NOT_CONTACT
        dnc.save()
        presidential = Election.objects.create(name="Élection présidentielle 2027")
        self.assertEqual(election_service.set_current(presidential), 1)  # the promise of MARTIN
        self.assertEqual(Address.objects.get(name="MARTIN").status, Status.TO_VISIT)
        self.assertEqual(Address.objects.get(name="LEROY").status, Status.DO_NOT_CONTACT)
        self.assertEqual(Election.objects.filter(is_current=True).get(), presidential)
        self.assertEqual(election_service.phrase(presidential), "pour l'élection présidentielle 2027")


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
            return Location("Pfarrwöhrde", "17") if query["street"] == "Pfarrwöhrde 17" else None

        addr = AddressNotGeolocated("", "", "Pfarrwörde", "17", "12524", "BERLIN")
        self.assertIsNone(geocoding.geocode_direct(addr, "DE", fake))
        known = geocoding.KnownStreets([("Pfarrwöhrde", "12524", "Berlin")])
        location = geocoding.geocode_corrected(addr, "DE", fake, known)
        self.assertEqual(geocoding.location_to_fields(addr, location)["address"], "Pfarrwöhrde 17")


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

        organization = Organization.objects.create(code="clear", name="Clear")
        user = User.objects.create_user(email="m@demo.test", organization=organization, is_approved=True)
        address = Address.objects.create(
            organization=organization, name="X", address="Rue 1", zip_code="10115", city="Berlin",
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
