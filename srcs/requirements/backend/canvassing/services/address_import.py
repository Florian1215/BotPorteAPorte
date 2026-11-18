"""Import of a voter list (LEC): "LEC" screen of the site admins, or `manage.py import_addresses`.

The file is the full, current list:
- the consular electoral list as exported by the consulate ("LEC communiquée", .xls / .xlsx): a few title
  lines, then the columns "Nom de naissance", "Nom d'usage", "Prénoms", "Date de naissance", ["Lieu de naissance",
  "Pays de naissance"], "Adresse de résidence", "Code postal" (postcode and city: "10115 Berlin"),
  "Adresse électronique". It has no coordinates: addresses are geocoded (see `services/geocoding.py`);
- or a JSON list of already geocoded entries: [{"id", "name", "first_names", "address", "zip_code", "city", "lat", "lon"}].

After an import:
- people not yet in the database are created;
- people already there are kept (with their visit status), re-enabled if they had been disabled, and moved if
  their address changed;
- people of the list absent from the file are *disabled*: never deleted (history and statistics stay),
  but hidden from everyone.

Kept from the list: name, first names, address, year of birth. Not kept: e-mail, place of birth, full date of
birth (only used, hashed, to recognise a person from one list to the next, even after a move).
"""
import hashlib
import io
import json
import logging
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd
from django.contrib.gis.geos import Point
from django.db import close_old_connections, transaction
from django.utils import timezone

from accounts.models import VoterList
from canvassing.addressutils import AddressNotGeolocated, sanitize_address
from canvassing.models import Address, AddressImport, GeocodeCache, Status, address_key
from canvassing.services import geocoding, scoring

log = logging.getLogger(__name__)

MAX_ERRORS_REPORTED = 20

LEC_COLUMNS = {
    "birth_name": "Nom de naissance",
    "usage_name": "Nom d'usage",
    "first_names": "Prénoms",
    "birth_date": "Date de naissance",
    "street": "Adresse de résidence",
    "postcode_city": "Code postal",
}


class ImportFileError(Exception):
    """The file as a whole cannot be imported."""


@dataclass
class Entry:
    key: str
    content_key: str  # name + first names + address: matches rows imported before stable keys existed
    person_key: str  # name + first names + postcode: last resort, rows whose address was spelled differently
    name: str
    first_names: str
    address: str
    zip_code: str
    city: str
    has_id: bool
    lat: float | None = None  # None: to geocode
    lon: float | None = None
    birth_year: int | None = None
    source_address: str = ""
    parsed: AddressNotGeolocated | None = None
    geocode_key: str = ""


@dataclass
class ImportReport:
    total: int = 0
    new: int = 0
    existing: int = 0
    moved: int = 0
    reactivated: int = 0
    disabled: int = 0
    invalid: int = 0
    errors: list[str] = field(default_factory=list)
    to_geocode: int = 0  # distinct addresses not geocoded yet (the slow part)
    not_geocoded: int = 0
    not_geocoded_examples: list[str] = field(default_factory=list)
    geocoding_warnings: list[str] = field(default_factory=list)  # e.g. Google refused (billing, quota)

    def as_dict(self) -> dict:
        return dict(self.__dict__)

    def error(self, message: str) -> None:
        self.invalid += 1
        if len(self.errors) < MAX_ERRORS_REPORTED:
            self.errors.append(message)


def person_key(name: str, first_names: str, zip_code: str) -> str:
    return "|".join(" ".join(str(p).lower().split()) for p in (name, first_names, zip_code))


def normalize_street(street: str) -> str:
    s = street.lower().replace("ß", "ss").replace("strasse", "str").replace("str.", "str")
    return re.sub(r"[\s.\-,]", "", s)


# --------------------------------------------------------------------------- reading files


def _cell(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return " ".join(str(value).split())


def read_lec(data: bytes, country_code: str, report: ImportReport) -> list[Entry]:
    try:
        raw = pd.read_excel(io.BytesIO(data), header=None, dtype=str)
    except Exception:  # noqa: BLE001 - any unreadable spreadsheet
        raise ImportFileError("Impossible de lire ce fichier Excel.") from None
    header_row = next(
        (i for i, row in raw.head(30).iterrows() if {LEC_COLUMNS["usage_name"], LEC_COLUMNS["street"]} <= {_cell(v) for v in row}),
        None,
    )
    if header_row is None:
        raise ImportFileError(
            "Colonnes introuvables : le fichier doit être la liste électorale consulaire, avec les colonnes "
            + ", ".join(f"« {c} »" for c in LEC_COLUMNS.values())
            + "."
        )
    columns = [_cell(v) for v in raw.iloc[header_row]]
    missing = [c for c in LEC_COLUMNS.values() if c not in columns]
    if missing:
        raise ImportFileError("Colonnes manquantes : " + ", ".join(f"« {c} »" for c in missing) + ".")
    index = {key: columns.index(name) for key, name in LEC_COLUMNS.items()}

    entries = []
    rows = raw.iloc[header_row + 1 :]
    for line, (_, row) in enumerate(rows.iterrows(), start=header_row + 2):
        values = {key: _cell(row.iloc[i]) for key, i in index.items()}
        if not any(values.values()):
            continue
        report.total += 1
        name = values["usage_name"] or values["birth_name"]
        if not name:
            report.error(f"Ligne {line} ignorée : nom manquant.")
            continue
        if not values["street"] or not values["postcode_city"]:
            report.error(f"Ligne {line} ignorée : adresse manquante.")
            continue
        parsed = sanitize_address(
            {
                "usage_name": name,
                "family_name": values["birth_name"],
                "first_names": values["first_names"],
                "street_name_number": values["street"],
                "postcode_city": values["postcode_city"],
            },
            country_code=country_code,
        )
        if parsed is None:
            report.error(f"Ligne {line} ignorée : code postal illisible (« {values['postcode_city']} »).")
            continue
        parsed = geocoding.number_first(parsed)
        birth = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", values["birth_date"])
        identity = f"{values['birth_name']}|{values['first_names']}|{values['birth_date']}".lower()
        has_id = bool(values["birth_name"] and birth)
        address = values["street"]
        content_key = address_key(name, values["first_names"], address, parsed.zip_str, parsed.city)
        entries.append(
            Entry(
                key="lec:" + hashlib.sha256(identity.encode()).hexdigest()[:40] if has_id else content_key,
                content_key=content_key,
                person_key=person_key(name, values["first_names"], parsed.zip_str),
                name=name[:255],
                first_names=values["first_names"][:255],
                address=address[:255],
                zip_code=parsed.zip_str[:16],
                city=parsed.city[:128],
                has_id=has_id,
                birth_year=int(birth.group(3)) if birth else None,
                source_address=f"{values['street']} | {values['postcode_city']}"[:512],
                parsed=parsed,
                geocode_key=geocoding.cache_key(parsed, country_code),
            )
        )
    return entries


def _text(raw: dict, key: str, required: bool = True, max_length: int = 255) -> str:
    value = raw.get(key)
    value = "" if value is None else str(value).strip()
    if required and not value:
        raise ValueError(f"champ « {key} » manquant")
    if len(value) > max_length:
        raise ValueError(f"champ « {key} » trop long")
    return value


def _coordinate(raw: dict, key: str, limit: float) -> float:
    try:
        value = float(raw[key])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"coordonnée « {key} » manquante ou invalide") from None
    if not -limit <= value <= limit:
        raise ValueError(f"coordonnée « {key} » hors limites")
    return value


def parse_json_entry(raw) -> Entry:
    """One element of a JSON file → Entry. Raises ValueError with a human-readable reason."""
    if not isinstance(raw, dict):
        raise ValueError("ce n'est pas un objet JSON")
    name = _text(raw, "name")
    first_names = _text(raw, "first_names", required=False)
    address = _text(raw, "address")
    zip_code = _text(raw, "zip_code", max_length=16)
    city = _text(raw, "city", max_length=128)
    external_id = _text(raw, "id", required=False, max_length=200)
    content_key = address_key(name, first_names, address, zip_code, city)
    return Entry(
        key=f"id:{external_id}" if external_id else content_key,
        content_key=content_key,
        person_key=person_key(name, first_names, zip_code),
        name=name,
        first_names=first_names,
        address=address,
        zip_code=zip_code,
        city=city,
        lat=_coordinate(raw, "lat", 90),
        lon=_coordinate(raw, "lon", 180),
        has_id=bool(external_id),
    )


def read_json(data: bytes, report: ImportReport) -> list[Entry]:
    try:
        content = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ImportFileError("Ce fichier n'est pas un JSON valide.") from None
    if isinstance(content, dict) and isinstance(content.get("addresses"), list):
        content = content["addresses"]
    if not isinstance(content, list):
        raise ImportFileError("Le fichier doit contenir une liste d'adresses (ou un objet avec une clé « addresses »).")
    entries = []
    for i, raw in enumerate(content, start=1):
        report.total += 1
        try:
            entries.append(parse_json_entry(raw))
        except ValueError as exc:
            report.error(f"Adresse n°{i} ignorée : {exc}.")
    return entries


def read_file(data: bytes, filename: str, country_code: str) -> tuple[list[Entry], ImportReport]:
    report = ImportReport()
    name = filename.lower()
    if name.endswith((".xls", ".xlsx")):
        entries = read_lec(data, country_code, report)
    elif name.endswith(".json"):
        entries = read_json(data, report)
    else:
        raise ImportFileError("Choisis la liste électorale consulaire (.xls ou .xlsx) ou un fichier .json.")
    if report.total and not entries:
        raise ImportFileError("Aucune adresse valide dans ce fichier : vérifie son format.")
    return entries, report


# --------------------------------------------------------------------------- matching


@dataclass
class Plan:
    report: ImportReport
    create: list[Entry] = field(default_factory=list)
    update: list[tuple[Address, Entry]] = field(default_factory=list)
    gone: list[int] = field(default_factory=list)

    def to_geocode(self) -> list[Entry]:
        return [e for e in self.create if e.lat is None] + [e for a, e in self.update if e.lat is None and _moved(a, e)]


def _moved(address: Address, entry: Entry) -> bool:
    """Has the person moved since the last import (or is it the first import of this kind of file)?"""
    if entry.lat is not None:  # JSON: coordinates given
        return (address.lat, address.lon) != (entry.lat, entry.lon)
    if address.source_address:
        return address.source_address != entry.source_address
    # Imported before `source_address` existed: compare with the stored (normalized) address.
    return not (
        normalize_street(address.address) == normalize_street(entry.address) and address.zip_code == entry.zip_code
    )


def plan_import(voter_list: VoterList, entries: list[Entry], report: ImportReport) -> Plan:
    plan = Plan(report=report)
    by_key: dict[str, list[Address]] = defaultdict(list)
    by_content: dict[str, list[Address]] = defaultdict(list)
    by_person: dict[str, list[Address]] = defaultdict(list)
    existing = list(Address.all_objects.filter(voter_list=voter_list).order_by("id"))
    for address in existing:
        by_key[address.source_key].append(address)
        by_content[address.compute_key()].append(address)
        by_person[person_key(address.name, address.first_names, address.zip_code)].append(address)
    taken: set[int] = set()

    def take(candidates: list[Address]) -> Address | None:
        for address in candidates:
            if address.id not in taken:
                taken.add(address.id)
                return address
        return None

    for entry in entries:
        match = take(by_key.get(entry.key, [])) or take(by_content.get(entry.content_key, [])) or take(by_person.get(entry.person_key, []))
        if match is None:
            report.new += 1
            plan.create.append(entry)
            continue
        report.existing += 1
        if match.disabled_at is not None:
            report.reactivated += 1
        if _moved(match, entry):
            report.moved += 1
        plan.update.append((match, entry))

    plan.gone = [a.id for a in existing if a.id not in taken and a.disabled_at is None]
    report.disabled = len(plan.gone)
    keys = {e.geocode_key for e in plan.to_geocode()}
    report.to_geocode = len(keys) - GeocodeCache.objects.filter(query__in=keys).count() if keys else 0
    return plan


def preview(voter_list: VoterList, data: bytes, filename: str) -> ImportReport:
    entries, report = read_file(data, filename, voter_list.country_code)
    return plan_import(voter_list, entries, report).report


# --------------------------------------------------------------------------- geocoding + saving


def geocode_plan(plan: Plan, country_code: str, progress=None) -> None:
    """Coordinates for the people to (re)locate. Those that cannot be located are left out (new people)
    or kept at their former address (people who moved)."""
    todo = plan.to_geocode()
    if not todo:
        return
    report = plan.report
    results = geocoding.geocode_many(
        {e.geocode_key: e.parsed for e in todo}, country_code, progress, warnings=report.geocoding_warnings
    )
    for entry in todo:
        row = results.get(entry.geocode_key)
        if row is not None and row.found:
            entry.lat, entry.lon = row.lat, row.lon
            entry.address = f"{row.street} {entry.parsed.street_number}".strip()[:255]
            entry.zip_code, entry.city = row.zip_code or entry.zip_code, row.city or entry.city
        else:
            report.not_geocoded += 1
            if len(report.not_geocoded_examples) < MAX_ERRORS_REPORTED:
                report.not_geocoded_examples.append(entry.parsed.to_str())
    not_found = {id(e) for e in todo if e.lat is None}
    report.new -= sum(1 for e in plan.create if id(e) in not_found)
    plan.create = [e for e in plan.create if id(e) not in not_found]


UPDATED_FIELDS = [
    "source_key", "disabled_at", "name", "first_names", "address", "zip_code", "city", "location", "birth_year",
    "source_address",
]


@transaction.atomic
def commit(voter_list: VoterList, plan: Plan) -> ImportReport:
    to_create = []
    for e in plan.create:
        to_create.append(
            Address(
                voter_list=voter_list,
                source_key=e.key,
                name=e.name,
                first_names=e.first_names,
                address=e.address,
                zip_code=e.zip_code,
                city=e.city,
                location=Point(e.lon, e.lat, srid=4326),
                birth_year=e.birth_year,
                source_address=e.source_address,
            )
        )
    to_update = []
    for address, e in plan.update:
        address.source_key = e.key
        address.disabled_at = None
        address.name = e.name
        if e.has_id or e.first_names:
            address.first_names = e.first_names
        if e.birth_year:
            address.birth_year = e.birth_year
        if _moved(address, e):
            if e.lat is not None:  # located: the person now lives there
                address.address, address.zip_code, address.city = e.address, e.zip_code, e.city
                address.location = Point(e.lon, e.lat, srid=4326)
                address.source_address = e.source_address
            # else: not found, the former address is kept (and retried at the next import)
        else:
            address.source_address = e.source_address
        to_update.append(address)

    Address.all_objects.bulk_create(to_create, batch_size=1000)
    Address.all_objects.bulk_update(to_update, UPDATED_FIELDS, batch_size=1000)
    disabled = Address.all_objects.filter(id__in=plan.gone, disabled_at__isnull=True)
    # Release reservations so that a re-enabled address does not come back stuck "in progress".
    disabled.filter(status=Status.PLANNED).update(status=Status.TO_VISIT, visit_planned_at=None, visit_planned_by=None)
    disabled.update(disabled_at=timezone.now())
    # The zones' density and ages count the French voters of the list: they changed with it.
    for organization in voter_list.organizations.all():
        scoring.rescore_organization(organization)
    return plan.report


def run_import(voter_list: VoterList, data: bytes, filename: str, progress=None) -> ImportReport:
    """Read, geocode and save (synchronously)."""
    entries, report = read_file(data, filename, voter_list.country_code)
    plan = plan_import(voter_list, entries, report)
    geocode_plan(plan, voter_list.country_code, progress)
    return commit(voter_list, plan)


def start_import(voter_list: VoterList, user, data: bytes, filename: str) -> AddressImport:
    """Run the import in a background thread (geocoding a whole list takes a while). The file is read
    right away (format errors are reported immediately) and never stored."""
    entries, report = read_file(data, filename, voter_list.country_code)
    job = AddressImport.objects.create(voter_list=voter_list, user=user, filename=filename[:255])
    threading.Thread(target=_run, args=(job.id, entries, report), daemon=True).start()
    return job


def _run(job_id: int, entries: list[Entry], report: ImportReport) -> None:
    close_old_connections()
    job = AddressImport.objects.select_related("voter_list").get(pk=job_id)
    voter_list = job.voter_list

    def progress(done, total):
        AddressImport.objects.filter(pk=job_id).update(geocode_done=done, geocode_total=total)

    try:
        plan = plan_import(voter_list, entries, report)
        AddressImport.objects.filter(pk=job_id).update(geocode_total=plan.report.to_geocode)
        geocode_plan(plan, voter_list.country_code, progress)
        job.report = commit(voter_list, plan).as_dict()
        job.status = AddressImport.ImportStatus.DONE
    except geocoding.GeocodingUnavailable as exc:
        job.status, job.message = AddressImport.ImportStatus.FAILED, f"Géocodage impossible ({exc}). Réessaie plus tard."
    except Exception as exc:  # noqa: BLE001 - reported to the user, details in the logs
        log.exception("Address import %s failed", job_id)
        job.status, job.message = AddressImport.ImportStatus.FAILED, f"Erreur inattendue : {exc}"
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "message", "report", "finished_at"])
    close_old_connections()
