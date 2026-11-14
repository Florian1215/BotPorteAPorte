"""Address geocoding with Nominatim (ported from the bot's `from_geopy_location`)."""
from django.conf import settings
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

from canvassing.addressutils import AddressNotGeolocated, StreetFormat, street_format_country_dict


def make_geocoder(domain: str | None = None, min_delay_seconds: float = 1.0):
    kwargs = {"user_agent": settings.NOMINATIM_USER_AGENT, "timeout": 10}
    domain = domain or settings.NOMINATIM_DOMAIN
    if domain:
        kwargs["domain"] = domain
    return RateLimiter(Nominatim(**kwargs).geocode, min_delay_seconds=min_delay_seconds)


def geocode(addr: AddressNotGeolocated, country_code: str | None, geocoder=None):
    """Geocode a parsed address. Returns a geopy Location or None."""
    geocoder = geocoder or make_geocoder()
    # Remove floor/flat number from street number, otherwise geolocation has issues
    street_number = addr.street_number.split("/")[0]
    query = {"street": f"{addr.street_name} {street_number}".strip(), "city": addr.city, "postalcode": addr.zip_str}
    kwargs = {"exactly_one": True, "addressdetails": True}
    if country_code:
        kwargs["country_codes"] = country_code.lower()
    return geocoder(query, **kwargs)


def location_to_fields(addr: AddressNotGeolocated, location) -> dict | None:
    """Normalize a Nominatim result into address fields. Returns None if the result is too imprecise."""
    details = location.raw.get("address", {})
    street = next((details[k] for k in ("road", "square", "hamlet", "village") if k in details), None)
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
