"""
A collection of methods to split, sanitize addresses, etc.
"""
import re
from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional


@dataclass
class AddressNotGeolocated:
    usage_name: str
    first_names: str
    street_name: str
    street_number: str # it's a string because some street numbers are e.g. "67A"
    zip_str: str
    city: str

    def to_str(self):
        return f"{self.street_name} {self.street_number}, {self.zip_str} {self.city}"


class StreetFormat(Enum):
    NUMBER_FIRST = auto()  # e.g. "3 rue de la forêt"
    NUMBER_LAST = auto()  # e.g. "Rostockerstr. 33"


street_format_country_dict = {
    'DE': StreetFormat.NUMBER_LAST,
    'AT': StreetFormat.NUMBER_LAST,
    'CZ': StreetFormat.NUMBER_LAST,
    'FR': StreetFormat.NUMBER_FIRST,
    'LU': StreetFormat.NUMBER_FIRST
}


def check_postcode(zip_str: str) -> bool:
    if not zip_str:
        return False

    return zip_str[0].isdigit()


STRASSE = r'[ẞßs]tra[ẞßs]+e'
# Accept any "strasse" pattern with 1 missing letter if it's at the end of the string
# (tolerate dots and spaces before the end character)
STRASSE_TYPOS = [
    re.compile(r'[ẞßs]ta[ẞßs]+e\.?\s*$', re.IGNORECASE),
    re.compile(r'[ẞßs]tr[ẞßs]+e\.?\s*$', re.IGNORECASE),
    re.compile(r'[ẞßs]tra[ẞßs]+\.?\s*$', re.IGNORECASE),
    re.compile(r'tra[ẞßs]+e\.?\s*$', re.IGNORECASE),
]
STR_SPACE_SEPARATED = re.compile(rf"\s+{STRASSE}", re.IGNORECASE)
STR_CONCATENATED = re.compile(STRASSE, re.IGNORECASE)


def strasse_to_str(street_name: str) -> Optional[str]:
    replaced, n_replacements = STR_SPACE_SEPARATED.subn(' Str.', street_name)
    if n_replacements == 0:
        replaced, n_replacements = STR_CONCATENATED.subn('str.', street_name)
        if n_replacements == 0:
            return None
    return replaced


def correct_strasse_type(street_name: str) -> Optional[str]:
    # try a bunch of likely typo corrections
    for typo in STRASSE_TYPOS:
        replaced, n_replacements = typo.subn('strasse', street_name)
        if n_replacements > 0:
            return replaced
    return None


def sanitize_address_germany(address: AddressNotGeolocated) -> Optional[AddressNotGeolocated]:
    # Return early if the postcode is wrong
    if not check_postcode(address.zip_str):
        return None

    # Replace wrong spellings of straße by str.
    sanitized_street_name = strasse_to_str(address.street_name)
    if sanitized_street_name is None:
        sanitized_street_name = correct_strasse_type(address.street_name)
        if sanitized_street_name:
            sanitized_street_name = strasse_to_str(sanitized_street_name)

    # It is potentially ok if we get None here. Examples:
    # - No "strasse" in the name, e.g. "Weg", "Brücke" etc.
    # - Street name already uses "str." format
    if sanitized_street_name:
        address.street_name = sanitized_street_name

    return address


def sanitize_address_austria(address: AddressNotGeolocated) -> Optional[AddressNotGeolocated]:
    if not check_postcode(address.zip_str):
        return None

    address = sanitize_address_germany(address)

    address.city = address.city.lower().replace("vienne", "wien")

    return address


def sanitize_address_czech_republic(address: AddressNotGeolocated) -> Optional[AddressNotGeolocated]:
    if not check_postcode(address.zip_str):
        return None

    return address


def sanitize_address_france(address: AddressNotGeolocated) -> Optional[AddressNotGeolocated]:
    if not check_postcode(address.zip_str):
        return None

    return address


def split_street_name_number(street_name_number: str, country_code: str) -> tuple[str, str]:
    """
    Splits the address into street name and number, and sanitize it
    """
    street_name_number = street_name_number.strip()

    street_format = street_format_country_dict.get(country_code, StreetFormat.NUMBER_LAST)
    if street_format == StreetFormat.NUMBER_LAST:
        regex_str = r'[\d]+'
    else:
        regex_str = r'[\D]+'

    regex_results = re.search(regex_str, street_name_number)
    if regex_results is None:
        # No street number found
        street_name = street_name_number
        street_number = ""
    else:
        res = regex_results.start() # Stop at first numeric character

        if street_format == StreetFormat.NUMBER_LAST:
            street_name = street_name_number[0 : res].strip()
            street_number = street_name_number[res:].strip()
        else:
            street_number = street_name_number[0 : res].strip()
            street_name = street_name_number[res:].strip()
            if street_name.startswith(',') and len(street_name) > 1:
                street_name = street_name[1:].strip()

    #print(f"{street_name_number}: {street_name}, {street_number}")
    return street_name, street_number


def split_postcode_city(postcode_city: str) -> tuple[str, str]:
    postcode_city = postcode_city.strip()
    m = re.match(r'(\D*\d+)(\D+)', postcode_city)
    if m is None:
        return None, None
    zip_str = m.group(1).strip()
    city = m.group(2).strip()

    # Remove non-numeric characters at beginning of zip code
    res = re.search(r'(\d+)', zip_str).start()
    zip_str = zip_str[res:]

    #print(f"{postcode_city}: {zip_str}, {city}")
    return zip_str, city


def sanitize_address(address_row, country_code: str = None) -> Optional[AddressNotGeolocated]:
    """
    :param address_row: row of the address dataframe. Must contain at least the columns `columns_required`
    :param country: str, country code to apply country-specific address sanitizing rules
    """
    if str(address_row["usage_name"]).lower().strip() == 'nan':
        usage_name = str(address_row["family_name"])
    else:
        usage_name = str(address_row["usage_name"])

    usage_name = usage_name.strip()

    if str(address_row["first_names"]).lower().strip() == 'nan':
        first_names = ""
    else:
        first_names = address_row["first_names"].strip()

    # Separating street name and number and sanitizing them
    street_name, street_number = split_street_name_number(
        street_name_number=address_row["street_name_number"],
        country_code=country_code)

    [zip_str, city] = split_postcode_city(address_row["postcode_city"])
    if zip_str is None:
        return None

    address = AddressNotGeolocated(
        usage_name=usage_name,
        first_names=first_names,
        street_name=street_name,
        street_number=street_number,
        zip_str=zip_str,
        city=city
    )

    if country_code == 'DE':
        return sanitize_address_germany(address=address)
    elif country_code == 'AT':
        return sanitize_address_austria(address=address)
    elif country_code == 'CZ':
        return sanitize_address_czech_republic(address=address)
    elif country_code == 'FR':
        return sanitize_address_france(address=address)
    else:
        return address
