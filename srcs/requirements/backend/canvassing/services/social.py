"""Social indicator uploaded by a responsable: the share of residents living on minimum social benefits, by
polling district, in one format for every city and country (examples in ./score_sociale).

A GeoJSON FeatureCollection, one feature per polling district:

    {"bureau_vote": "11101",            # number of the polling district (as in the imported zones)
     "minima_sociaux_pct": 9.1,         # % of the residents on minimum social benefits
     "indicateur": "« Transferquote » …",  # what the figure is (optional, shown in the app)
     "date_donnees": "2025"}            # date of the data (optional)

plus the outline of the district (used when the numbers do not match the imported zones). The English names of
the Berlin file (`district_id`, `rate`, `indicator`, `data_date`) are read too.

The values are saved on the organization (`social_upload`), so re-importing the city pack keeps them.
"""
import json
from dataclasses import dataclass, field

from django.contrib.gis.geos import GEOSException, GEOSGeometry
from django.db import transaction
from django.utils import timezone

from ..models import District
from . import scoring
from .packs import key

SOCIAL_LABEL = "Minima sociaux (% des habitants)"
CODE_FIELDS = ("bureau_vote", "district_id", "code")
VALUE_FIELDS = ("minima_sociaux_pct", "rate", "value")
INDICATOR_FIELDS = ("indicateur", "indicator")
DATE_FIELDS = ("date_donnees", "data_date")


class SocialFileError(Exception):
    pass


@dataclass
class SocialEntry:
    code: str
    value: float
    geometry: GEOSGeometry | None


@dataclass
class SocialFile:
    entries: list[SocialEntry] = field(default_factory=list)
    indicator: str = ""
    date: str = ""


def _first(props: dict, names: tuple[str, ...]):
    for name in names:
        if props.get(name) not in (None, ""):
            return props[name]
    return None


def _number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", ".").replace("%", "").strip())
    except ValueError:
        return None
    return number if number == number else None  # NaN


def parse(data: bytes) -> SocialFile:
    try:
        collection = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SocialFileError("Le fichier doit être un GeoJSON (.geojson) : il n'a pas pu être lu.") from None
    features = collection.get("features") if isinstance(collection, dict) else None
    if not isinstance(features, list) or not features:
        raise SocialFileError("Aucun bureau de vote dans le fichier (GeoJSON « FeatureCollection » attendu).")

    result = SocialFile()
    for feature in features:
        props = (feature or {}).get("properties") or {}
        code, value = _first(props, CODE_FIELDS), _number(_first(props, VALUE_FIELDS))
        if code is None or value is None:
            continue
        geometry = None
        if feature.get("geometry"):
            try:
                geometry = GEOSGeometry(json.dumps(feature["geometry"]), srid=4326)
            except (GEOSException, ValueError, TypeError):
                geometry = None
        result.entries.append(SocialEntry(str(code).strip(), value, geometry))
        result.indicator = result.indicator or str(_first(props, INDICATOR_FIELDS) or "").strip()
        result.date = result.date or str(_first(props, DATE_FIELDS) or "").strip()
    if not result.entries:
        raise SocialFileError(
            "Aucune valeur lue : chaque bureau doit avoir « bureau_vote » (numéro du bureau) "
            "et « minima_sociaux_pct » (% des habitants aux minima sociaux)."
        )
    return result


def match(districts: list[District], social: SocialFile) -> dict[int, float]:
    """District id → value: by polling district number, else the file's outline containing the district."""
    by_code = {key(e.code): e.value for e in social.entries}
    values, unmatched = {}, []
    for d in districts:
        value = by_code.get(key(d.code))
        if value is None:
            unmatched.append(d)
        else:
            values[d.id] = value
    outlines = [(e.geometry.prepared, e.geometry.extent, e.value) for e in social.entries if e.geometry]
    for d in unmatched:
        point = d.label_point
        if point is None:
            continue
        for prepared, (xmin, ymin, xmax, ymax), value in outlines:
            if xmin <= point.x <= xmax and ymin <= point.y <= ymax and prepared.contains(point):
                values[d.id] = value
                break
    return values


def check_same_city(districts: list[District], social: SocialFile) -> None:
    """Numbers alone can match by chance (bureau "10101" exists in many cities): the file's outlines must cover
    the zones."""
    extents = [e.geometry.extent for e in social.entries if e.geometry]
    points = [d.label_point for d in districts if d.label_point is not None]
    if not extents or not points:
        return
    xmin, ymin = min(e[0] for e in extents), min(e[1] for e in extents)
    xmax, ymax = max(e[2] for e in extents), max(e[3] for e in extents)
    inside = sum(xmin <= p.x <= xmax and ymin <= p.y <= ymax for p in points)
    if inside < len(points) / 2:
        raise SocialFileError("Les bureaux de ce fichier sont ailleurs que tes zones : ce n'est pas le fichier de ta ville.")


@transaction.atomic
def import_file(organization, data: bytes, filename: str) -> dict:
    social = parse(data)
    districts = list(District.objects.filter(organization=organization).only("id", "code", "label_point"))
    if not districts:
        raise SocialFileError("Importe d'abord les zones (pack de la ville) : l'indicateur social s'y rattache.")
    check_same_city(districts, social)
    values = match(districts, social)
    if not values:
        raise SocialFileError(
            "Aucun bureau du fichier ne correspond aux zones importées (ni par numéro, ni par contour). "
            "Vérifie que c'est bien le fichier de ta ville."
        )
    codes = {d.id: d.code for d in districts}
    organization.social_upload = {
        "filename": filename[:255],
        "indicator": social.indicator[:1000],
        "date": social.date[:64],
        "uploaded_at": timezone.now().isoformat(),
        "values": {codes[pk]: value for pk, value in values.items()},
    }
    organization.save(update_fields=["social_upload"])
    apply_saved(organization)
    return {
        "n_districts": len(districts),
        "n_with_social": len(values),
        "n_in_file": len(social.entries),
        "indicator": social.indicator,
        "date": social.date,
    }


def apply_saved(organization) -> int | None:
    """Put the uploaded values on the districts (also after re-importing the pack). None: nothing uploaded."""
    values = (organization.social_upload or {}).get("values")
    if not values:
        return None
    districts = list(District.objects.filter(organization=organization).only("id", "code", "social_value"))
    for d in districts:
        d.social_value = values.get(d.code)
    District.objects.bulk_update(districts, ["social_value"], batch_size=500)
    organization.social_label = SOCIAL_LABEL
    organization.social_higher_is_poorer = True
    organization.save(update_fields=["social_label", "social_higher_is_poorer"])
    scoring.rescore_organization(organization)
    return sum(d.social_value is not None for d in districts)


def upload_to_dict(organization) -> dict | None:
    upload = organization.social_upload or {}
    if not upload.get("values"):
        return None
    return {k: upload.get(k, "") for k in ("filename", "indicator", "date", "uploaded_at")} | {
        "n_values": len(upload["values"])
    }
