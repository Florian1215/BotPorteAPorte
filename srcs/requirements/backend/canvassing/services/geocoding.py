"""Address geocoding with Nominatim (ported from the bot's `from_geopy_location`).

Addresses of the electoral lists are typed by hand and often have typos ("Haupstr.", "Argentinische Alle",
"GÖRREstr."). An address is looked up in this order, the first hit wins:
1. Nominatim, as written;
2. Nominatim, cleaned up (abbreviations, case, "OT …" districts, "172 a");
3. Nominatim without the postcode (postcode typo), kept only if the hit is one digit away from it;
   Then a free-text search (villages without street names, "Harbach 86"; odd spellings), kept only if it is the
   same house number, next to the given postcode, on a street (or place) with a similar name;
4. typo correction: the closest street name already located in the same postcode (or town), on Nominatim;
5. optionally, a self-hosted Photon server (typo-tolerant search, like the search box of a map site): its hit is
   only accepted in the same postcode (or town).
"""
import difflib
import re
import threading

from django.conf import settings
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim, Photon

from canvassing.addressutils import AddressNotGeolocated, StreetFormat, street_format_country_dict


def make_geocoder(domain: str | None = None, min_delay_seconds: float = 1.0):
    kwargs = {"user_agent": settings.NOMINATIM_USER_AGENT, "timeout": 10}
    domain = domain or settings.NOMINATIM_DOMAIN
    if domain:
        kwargs["domain"] = domain
    return RateLimiter(Nominatim(**kwargs).geocode, min_delay_seconds=min_delay_seconds)


def _stem(street: str) -> str:
    """"Görres-Straße" → "görres": what tells two street names apart (the generic "straße" inflates similarity)."""
    name = street.strip().lower()
    for a, b in (("ß", "ss"), ("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("é", "e"), ("è", "e")):
        name = name.replace(a, b)
    name = re.sub(r"(strasse|str\.?)$", "", name)
    return re.sub(r"[\s\-.,']", "", name)


def same_street(found: str | None, typed: str) -> bool:
    """A hit is only kept if its street looks like the typed one (Nominatim sometimes returns another street)."""
    if not found:
        return False
    b = _stem(clean_street(typed))
    # Bilingual names: "Lotzestraße - Lotzowa".
    for part in re.split(r"\s+-\s*|\s*-\s+|;", found):
        a = _stem(part)
        if a == b or (min(len(a), len(b)) >= 3 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.75):
            return True
    return False


# Where Nominatim puts the "street" of an address. Villages (mostly in Austria) have no street names: the house
# number goes with the place ("Harbach 86", "Markt 7").
STREET_KEYS = ("road", "square", "place", "hamlet", "isolated_dwelling", "locality", "village", "neighbourhood")


def _street_of(details: dict, typed: str | None = None) -> str | None:
    """The street (or place) of a Nominatim result: the one looking like the typed street if several are given."""
    names = [details[k] for k in STREET_KEYS if details.get(k)]
    if typed:
        for name in names:
            if same_street(name, typed):
                return name
    return names[0] if names else None


def _nominatim(geocoder, street_name: str, street_number: str, zip_code: str, city: str, country_code: str | None,
               typed: str | None = None):
    # Remove floor/flat number from street number, otherwise geolocation has issues
    street_number = street_number.split("/")[0]
    query = {"street": f"{street_name} {street_number}".strip(), "city": city, "postalcode": zip_code}
    kwargs = {"exactly_one": True, "addressdetails": True}
    if country_code:
        kwargs["country_codes"] = country_code.lower()
    location = geocoder(query, **kwargs)
    if location is None:
        return None
    details = location.raw.get("address", {})
    typed = typed or street_name
    road = _street_of(details, typed)
    if same_street(road, typed):
        return location
    # A renamed street is found under its former name ("Wissmannstraße" → "Lucy-Lameck-Straße"): keep the hit
    # if it is the right house and the street it is on used to have the typed name.
    if road and _same_number(details.get("house_number"), street_number):
        street = geocoder({"street": road, "postalcode": details.get("postcode") or zip_code}, namedetails=True, **kwargs)
        names = (street.raw.get("namedetails") or {}) if street else {}
        if any(same_street(n, typed) for key, value in names.items() if "old_name" in key for n in value.split(";")):
            return location
    return None


def geocode(addr: AddressNotGeolocated, country_code: str | None, geocoder=None):
    """Geocode a parsed address as written. Returns a geopy Location or None."""
    geocoder = geocoder or make_geocoder()
    return _nominatim(geocoder, addr.street_name, addr.street_number, addr.zip_str, addr.city, country_code, addr.street_name)


# --------------------------------------------------------------------------- cleaning hand-typed addresses

_STREET_FIXES = [
    (re.compile(r"(?i)str\.r(?=\s|$)"), "straßer"),  # Vienna: "Landstr.r Hauptstr." → "Landstraßer Hauptstraße"
    (re.compile(r"(?i)stra(?:b|ss)e(?=\s|$)"), "straße"),  # "Hauptstrabe" (ß typed as b), "Hauptstrasse"
    (re.compile(r"(?i)(?<=\w)str(?:\.|asse|aße)?$"), "straße"),  # "Görrestr." → "Görrestraße"
    (re.compile(r"(?i)-str(?:\.|asse|aße)?$"), "-Straße"),  # "Theodor-Storm-str." → "Theodor-Storm-Straße"
    (re.compile(r"(?i)\bstra?(?:\.|sse)?(?=\s|$)"), "Straße"),  # "Leinder Str." / "Stra" → "Leinder Straße"
    (re.compile(r"(?i)\balle(?=\s|$)"), "Allee"),  # "Argentinische Alle" → "Argentinische Allee"
    (re.compile(r"(?i)\bpl\.(?=\s|$)"), "Platz"),
]


def _fix_case(text: str) -> str:
    """"GÖRREstr" / "LEINDER" → "Görrestr" / "Leinder" (words with 2+ capitals in a row are lowercased)."""
    def fix(word: str) -> str:
        return "-".join(p.capitalize() for p in word.split("-")) if re.search(r"[A-ZÄÖÜ]{2}", word) else word

    return " ".join(fix(w) for w in text.split())


# A street name ends with one of these (used to find it in "c/o Jane Doe Westerfeldstr.").
_STREET_END = r"(?:str\.?|straße|strasse|weg|gasse|allee|platz|ring|damm|ufer|steig|zeile)"


def clean_street(name: str) -> str:
    name = " ".join(name.split())
    # "c/o Manuela Jannarelli Westerfeldstr." → "Westerfeldstr." (someone else's name before the street).
    name = re.sub(rf"(?i)^c/o\s+(?:\S+\s+)*?(?=\S*{_STREET_END}(?:\s|$))", "", name)
    # "Schachendorf Nr." → "Schachendorf" (the number is in its own field).
    name = re.sub(r"(?i)\s*\bnr\s*\.?(?=\s|$)", "", name)
    name = _fix_case(name).strip(" ,;.")
    name = re.sub(r"(?i)\bbgm\.?\s*-?\s*", "Bürgermeister-", name)
    for pattern, repl in _STREET_FIXES:
        name = pattern.sub(repl, name)
    return name


def clean_number(number: str) -> str:
    """"172 a" → "172a", "12/3" → "12", "2F-K" → "2F", and the flat after the house number:
    "4 b Top 7" → "4b", "3 DG" → "3", "4 Whg 313" → "4", "1 OT Hoppenrade" → "1"."""
    first = number.split("/")[0]
    match = re.match(r"\s*(\d+)\s?([a-zA-Z](?![a-zA-Z]))?", first)
    if match:
        return match.group(1) + (match.group(2) or "")
    return re.sub(r"\s+", "", first)


def street_variants(street: str) -> list[str]:
    """Other usual spellings of a cleaned street name, to try one after the other.

    "Bayerischestraße" → "Bayerische Straße", "Freibergstraße" → "Freiberger Straße",
    "Rudolf Breitscheid Straße" → "Rudolf-Breitscheid-Straße".
    """
    variants = [street]
    glued = re.match(r"^(.*\w)(straße|allee|gasse|platz|damm|ufer|weg)$", street, flags=re.I)
    if glued:
        stem, suffix = glued.group(1), glued.group(2).capitalize()
        if suffix != "Weg":  # "Panoramaweg" is right as it is
            variants.append(f"{stem} {suffix}")  # "Schönhauserallee" → "Schönhauser Allee"
        if suffix == "Straße" and not stem.endswith(("e", "er")):
            variants.append(f"{stem}er Straße")
        words = [w for w in re.split(r"[\s-]+", stem) if w]
        if len(words) >= 2:  # named after someone: "Otto-Bauergasse", "Franz Emrichgasse" → "Franz-Emrich-Gasse"
            variants.append("-".join(words + [suffix]))
    words = street.replace("-", " ").split()
    if len(words) >= 3 and words[-1] == "Straße":
        variants.append("-".join(words))
    if len(words) == 2 and words[1].lower() in ("allee", "gasse", "platz", "damm", "ufer", "weg", "ring"):
        variants.append(words[0] + words[1].lower())  # "Lissabon Allee" → "Lissabonallee"
    if "-" in street:
        variants.append(street.replace("-", " "))
    return list(dict.fromkeys(variants))


def clean_city(city: str) -> str:
    """"CHEMNITZ OT WITTGENSDORF" → "Chemnitz", "PETERSAHGEN / EGGENSDORF" → "Petersahgen"."""
    city = re.split(r"\s+(?:OT|Ortsteil)\s+|\s*/\s*|,", city, maxsplit=1, flags=re.I)[0]
    return _fix_case(" ".join(city.split()))


def _same_number(found: str | None, wanted: str) -> bool:
    return bool(found) and clean_number(found).lower() == clean_number(wanted).lower()


def _similar(a: str, b: str) -> bool:
    a, b = a.lower().strip(), b.lower().strip()
    return bool(a and b) and (a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.75)


class _Hit:
    """A Photon result shaped like a Nominatim one (what `location_to_fields` reads)."""

    def __init__(self, props: dict, lat: float, lon: float):
        self.latitude, self.longitude = lat, lon
        self.raw = {"address": {
            "road": props.get("street") or props.get("name"),
            "house_number": props.get("housenumber"),
            "postcode": props.get("postcode"),
            "city": props.get("city") or props.get("district") or props.get("county"),
            "country_code": (props.get("countrycode") or "").lower(),
        }}


def make_photon():
    """Optional typo-tolerant search (a Photon server: self-hosted, the public one blocks bulk use)."""
    domain = settings.PHOTON_DOMAIN
    if not domain:
        return None
    return RateLimiter(
        Photon(domain=domain, user_agent=settings.NOMINATIM_USER_AGENT, timeout=10).geocode,
        min_delay_seconds=0.3, max_retries=0, swallow_exceptions=False,
    )


class PhotonUnavailable(Exception):
    """Photon did not answer: the address is not cached as "not found", the next import retries it."""


def _close_zip(a: str | None, b: str) -> bool:
    """Same postcode, or one digit off (a typo in the postcode)."""
    return bool(a) and len(a) == len(b) and sum(x != y for x, y in zip(a, b)) <= 1


def number_first(addr: AddressNotGeolocated) -> AddressNotGeolocated:
    """"" + "46 Alt-Moabit" (number written before the street) → "Alt-Moabit" + "46"."""
    match = re.match(r"^(\d+\s?[a-zA-Z]?)\s+(\D{3,})$", addr.street_number.strip())
    if addr.street_name.strip() or not match:
        return addr
    return AddressNotGeolocated(addr.usage_name, addr.first_names, match.group(2), match.group(1), addr.zip_str, addr.city)


def geocode_direct(addr: AddressNotGeolocated, country_code: str | None, geocoder):
    """Steps that only need Nominatim: as written, cleaned up, then without the postcode (postcode typo)."""
    location = geocode(addr, country_code, geocoder)
    if location:
        return location
    street, number, city = clean_street(addr.street_name), clean_number(addr.street_number), clean_city(addr.city)
    if not street or not number:
        return None  # no street number: no door to knock on
    for variant in street_variants(street):
        if (variant, number, city) != (addr.street_name, addr.street_number, addr.city):
            location = _nominatim(geocoder, variant, number, addr.zip_str, city, country_code)
            if location:
                return location
        if addr.zip_str:  # town misspelled ("DRESEDEN") or a district instead of the town: the postcode is enough
            location = _nominatim(geocoder, variant, number, addr.zip_str, "", country_code)
            if location:
                return location
    if addr.zip_str and city:
        location = _nominatim(geocoder, street, number, "", city, country_code)
        # Several towns/districts have the same street name: only keep a hit next to the given postcode.
        if location and _close_zip(location.raw.get("address", {}).get("postcode"), addr.zip_str):
            return location
    return _free_text(geocoder, street, number, addr.zip_str, city, country_code, addr.street_name)


def _free_text(geocoder, street: str, number: str, zip_code: str, city: str, country_code: str | None, typed: str):
    """One free-text search ("Harbach 86, 5630 Bad Hofgastein"), as typed in a map's search box. Kept only if it
    is the same house number, on a street (or place) with a similar name, in the same postcode (or town)."""
    kwargs = {"exactly_one": True, "addressdetails": True}
    if country_code:
        kwargs["country_codes"] = country_code.lower()
    location = geocoder(f"{street} {number}, {zip_code} {city}".strip(" ,"), **kwargs)
    if location is None:
        return None
    details = location.raw.get("address", {})
    town = next((details[k] for k in ("city", "town", "village", "municipality") if details.get(k)), "")
    if not _same_number(details.get("house_number"), number):
        return None
    if not (same_street(_street_of(details, typed), typed) or same_street(_street_of(details, street), street)):
        return None
    if not (_close_zip(details.get("postcode"), zip_code) or (not zip_code and _similar(town, city))):
        return None
    return location


class KnownStreets:
    """Street names already located (geocoding cache), by postcode and by town: the spelling reference."""

    def __init__(self, rows):
        self.by_zip: dict[str, set[str]] = {}
        self.by_city: dict[str, set[str]] = {}
        for street, zip_code, city in rows:
            if street:
                self.by_zip.setdefault(zip_code, set()).add(street)
                self.by_city.setdefault(city.lower(), set()).add(street)

    @classmethod
    def load(cls, zip_codes=None):
        from canvassing.models import GeocodeCache

        rows = GeocodeCache.objects.filter(found=True)
        if zip_codes is not None:
            rows = rows.filter(zip_code__in=list(zip_codes))
        return cls(rows.values_list("street", "zip_code", "city").distinct())

    def correct(self, street: str, zip_code: str, city: str) -> list[str]:
        """Likely right spellings of a mistyped street name, best first."""
        wanted = _stem(street)
        found: list[str] = []
        for names, cutoff in ((self.by_zip.get(zip_code, set()), 0.75), (self.by_city.get(city.lower(), set()), 0.85)):
            stems: dict[str, str] = {}
            for name in names:
                stems.setdefault(_stem(name), name)
            for match in difflib.get_close_matches(wanted, list(stems), n=2, cutoff=cutoff):
                if stems[match] not in found and match != wanted:
                    found.append(stems[match])
        return found[:3]


def geocode_corrected(addr: AddressNotGeolocated, country_code: str | None, geocoder, known: KnownStreets, photon=None):
    """Steps for a mistyped street name: closest known street of the same postcode/town, then Photon."""
    street, number, city = clean_street(addr.street_name), clean_number(addr.street_number), clean_city(addr.city)
    for fixed in known.correct(street, addr.zip_str, city):
        location = _nominatim(geocoder, fixed, number, addr.zip_str, city, country_code, addr.street_name)
        if location:
            return location

    if not photon or not street:
        return None
    try:
        results = photon(f"{street} {number}, {addr.zip_str} {city}".strip(" ,"), exactly_one=False, limit=5) or []
    except Exception as exc:
        raise PhotonUnavailable(str(exc)) from exc
    for result in results:
        props = result.raw.get("properties", {})
        if country_code and (props.get("countrycode") or "").upper() != country_code.upper():
            continue
        # Never move someone to another town: same postcode, or (postcode typo) a town with a similar name.
        if not ((addr.zip_str and props.get("postcode") == addr.zip_str) or _similar(props.get("city") or "", city)):
            continue
        if props.get("type") == "house" and _same_number(props.get("housenumber"), number) and same_street(props.get("street"), street):
            return _Hit(props, result.latitude, result.longitude)
        fixed_street = props.get("street") or (props.get("name") if props.get("type") == "street" else None)
        if fixed_street and fixed_street.lower() != street.lower():
            location = _nominatim(
                geocoder, fixed_street, number, props.get("postcode") or addr.zip_str, props.get("city") or city, country_code,
                addr.street_name,
            )
            if location:
                return location
    return None


def geocode_fuzzy(addr: AddressNotGeolocated, country_code: str | None, geocoder=None):
    """Geocode one hand-typed address with every step (see the module docstring)."""
    geocoder = geocoder or make_geocoder()
    location = geocode_direct(addr, country_code, geocoder)
    if location:
        return location
    try:
        return geocode_corrected(addr, country_code, geocoder, KnownStreets.load([addr.zip_str]), make_photon())
    except PhotonUnavailable:
        return None


def location_to_fields(addr: AddressNotGeolocated, location) -> dict | None:
    """Normalize a Nominatim result into address fields. Returns None if the result is too imprecise."""
    details = location.raw.get("address", {})
    street = _street_of(details, addr.street_name)
    city = next(
        (details[k] for k in ("city", "town", "village", "municipality", "suburb", "neighbourhood") if k in details),
        None,
    )
    house_number = addr.street_number or details.get("house_number")
    postcode = details.get("postcode")
    if not (street and city and house_number and postcode):
        return None

    country_code = details.get("country_code", "").upper()
    if street_format_country_dict.get(country_code, StreetFormat.NUMBER_LAST) == StreetFormat.NUMBER_LAST:
        address = f"{street} {house_number}"
    else:
        address = f"{house_number} {street}"

    return {
        "address": address,
        "zip_code": postcode,
        "city": city,
        "lat": location.latitude,
        "lon": location.longitude,
    }


class GeocodingUnavailable(Exception):
    """The geocoding service could not be reached (as opposed to "address not found")."""


def geocode_address(address: str, zip_code: str, city: str, country_code: str | None) -> tuple[float, float] | None:
    """(lat, lon) of a street address, or None if it cannot be found precisely (same rule as the imports)."""
    from canvassing.addressutils import split_street_name_number

    street_name, street_number = split_street_name_number(address, country_code=country_code)
    parsed = AddressNotGeolocated("", "", street_name, street_number, zip_code, city)
    try:
        location = geocode_fuzzy(parsed, country_code)
    except Exception as exc:  # network / service errors from geopy
        raise GeocodingUnavailable(str(exc)) from exc
    fields = location_to_fields(parsed, location) if location else None
    return (fields["lat"], fields["lon"]) if fields else None


# --------------------------------------------------------------------------- batch geocoding (list imports)

# Nominatim servers of the movement, one per country (no rate limit, unlike the public nominatim.openstreetmap.org).
NOMINATIM_SERVERS = {
    "DE": "nominatimdeutschland.okras.eu:443",
    "AT": "nominatimaustria.okras.eu:443",
    "CZ": "nominatimczechia.okras.eu:443",
    "FR": "nominatimfrance.okras.eu:443",
    "LU": "nominatimluxemburg.okras.eu:443",
}
BATCH_WORKERS = 4


def server_for(country_code: str | None) -> tuple[str | None, float]:
    """(Nominatim domain, min delay between requests) for a country: NOMINATIM_DOMAIN wins when set."""
    if settings.NOMINATIM_DOMAIN:
        return settings.NOMINATIM_DOMAIN, 0.0
    server = NOMINATIM_SERVERS.get((country_code or "").upper())
    return (server, 0.0) if server else (None, 1.0)  # public server: 1 request per second at most


def cache_key(addr: AddressNotGeolocated, country_code: str | None) -> str:
    number = addr.street_number.split("/")[0].strip()
    return "|".join(" ".join(p.lower().split()) for p in ((country_code or ""), addr.street_name, number, addr.zip_str, addr.city))[:512]


def geocode_many(addresses: dict[str, AddressNotGeolocated], country_code: str | None, progress=None) -> dict:
    """Geocode many parsed addresses (key → address), using and filling `GeocodeCache`.

    Returns key → GeocodeCache row (`found` False when the address could not be located precisely).
    `progress(done, total)` is called from time to time with the number of addresses looked up.
    """
    from concurrent.futures import ThreadPoolExecutor

    from canvassing.models import GeocodeCache

    results = {c.query: c for c in GeocodeCache.objects.filter(query__in=list(addresses))}
    missing = [k for k in addresses if k not in results]
    domain, delay = server_for(country_code)
    workers = BATCH_WORKERS if delay == 0 else 1
    local = threading.local()
    photon = make_photon()

    def to_row(key: str, addr: AddressNotGeolocated, location) -> GeocodeCache:
        fields = location_to_fields(addr, location) if location else None
        if not fields:
            return GeocodeCache(query=key, found=False)
        street = fields["address"]
        if addr.street_number and street.endswith(addr.street_number):
            street = street[: -len(addr.street_number)].strip()
        elif addr.street_number and street.startswith(addr.street_number):
            street = street[len(addr.street_number):].strip()
        return GeocodeCache(
            query=key, found=True, street=street[:255], zip_code=fields["zip_code"][:16], city=fields["city"][:128],
            lat=fields["lat"], lon=fields["lon"],
        )

    def geocoder():
        if not hasattr(local, "geocoder"):
            local.geocoder = make_geocoder(domain=domain, min_delay_seconds=delay)
        return local.geocoder

    def direct(key: str) -> GeocodeCache:
        try:
            location = geocode_direct(addresses[key], country_code, geocoder())
        except Exception as exc:  # network / server error: not cached, the next import retries
            raise GeocodingUnavailable(str(exc)) from exc
        return to_row(key, addresses[key], location)

    known: KnownStreets | None = None

    def corrected(key: str) -> GeocodeCache | None:
        try:
            location = geocode_corrected(addresses[key], country_code, geocoder(), known, photon)
        except PhotonUnavailable:
            return None  # left uncached
        except Exception as exc:
            raise GeocodingUnavailable(str(exc)) from exc
        return to_row(key, addresses[key], location)

    # Pass 1: Nominatim. Pass 2, for what was not found: typo correction, using the streets found so far
    # (the same list usually has the street spelled right for the neighbours).
    total = len(missing)
    done = 0
    failures = 0
    batch: list[GeocodeCache] = []
    not_found: list[str] = []

    def flush(force=False):
        if batch and (force or len(batch) >= 200):
            GeocodeCache.objects.bulk_create(batch, ignore_conflicts=True)
            batch.clear()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for key, row in zip(missing, pool.map(lambda k: _safe(direct, k), missing)):
            done += 1
            if row is None:
                failures += 1
                if failures >= 50 and failures > done / 2:
                    raise GeocodingUnavailable("le service de géocodage ne répond pas")
            elif row.found:
                results[key] = row
                batch.append(row)
            else:
                not_found.append(key)
            flush()
            if progress and done % 50 == 0:
                progress(done - len(not_found), total)  # the not found ones go through pass 2
        flush(force=True)

        if not_found:
            known = KnownStreets.load()
            base = done - len(not_found)
            for i, (key, row) in enumerate(zip(not_found, pool.map(lambda k: _safe(corrected, k), not_found)), 1):
                if row is not None:
                    results[key] = row
                    batch.append(row)
                flush()
                if progress and i % 20 == 0:
                    progress(base + i, total)
    flush(force=True)
    if progress:
        progress(total, total)
    return results


def _safe(fn, key):
    try:
        return fn(key)
    except GeocodingUnavailable:
        return None
