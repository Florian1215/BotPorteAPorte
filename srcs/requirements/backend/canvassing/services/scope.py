"""Which addresses an organization works on: those of its voter list (LEC) around its city.

Several organizations can share one list (e.g. Berlin and Leipzig, both on the Berlin consulate's list): the
addresses and their visits are shared, and each organization only sees the ones within `radius_km` of its city.
"""
from django.contrib.gis.geos import Polygon
from django.db.models import BooleanField, QuerySet
from django.db.models.expressions import RawSQL

from accounts.models import Organization

from ..models import Address
from .geo import bbox_around


def organization_addresses(organization: Organization | None, queryset: QuerySet | None = None) -> QuerySet:
    """Addresses of the organization (active ones by default; pass `Address.all_objects.all()` for every one)."""
    queryset = Address.objects.all() if queryset is None else queryset
    if organization is None or organization.voter_list_id is None:
        return queryset.none()
    queryset = queryset.filter(voter_list_id=organization.voter_list_id)
    if organization.city_lat is None or organization.city_lon is None:
        return queryset  # no city: the whole list
    center = (organization.city_lat, organization.city_lon)
    return (
        queryset.filter(location__within=Polygon.from_bbox(bbox_around([center], organization.radius_km)))
        .alias(
            in_radius=RawSQL(
                "ST_DWithin(location::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)",
                (organization.city_lon, organization.city_lat, organization.radius_km * 1000),
                output_field=BooleanField(),
            )
        )
        .filter(in_radius=True)
    )


# Same rule in raw SQL, for an address `a` and an organization `o` (accounts_organization).
ADDRESS_IN_ORGANIZATION_SQL = """
    a.voter_list_id = o.voter_list_id
    AND (
        o.city_lat IS NULL OR o.city_lon IS NULL
        OR ST_DWithin(a.location::geography, ST_SetSRID(ST_MakePoint(o.city_lon, o.city_lat), 4326)::geography, o.radius_km * 1000)
    )
"""
