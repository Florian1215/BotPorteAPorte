"""Django admin. No map widgets: they load tiles straight from openstreetmap.org, which blocks such use.
Addresses are geocoded from their fields; zones are drawn in the app (Zones screen)."""
from django import forms
from django.contrib import admin
from django.contrib.gis.geos import Point
from django.utils.html import format_html

from .models import Address, District, Tour, TourStop, Visit
from .services.geocoding import GeocodingUnavailable, geocode_address


class AddressAdminForm(forms.ModelForm):
    """The position is computed from street + postcode + city when they change ("Adresse introuvable" otherwise)."""

    class Meta:
        model = Address
        exclude = ["location"]

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        located_fields = ("address", "zip_code", "city", "organization")
        if self.instance.pk and self.instance.location and not any(f in self.changed_data for f in located_fields):
            return cleaned
        organization = cleaned.get("organization")
        try:
            position = geocode_address(
                cleaned["address"], cleaned["zip_code"], cleaned["city"], organization.country_code if organization else None
            )
        except GeocodingUnavailable:
            raise forms.ValidationError("Le service de géocodage est indisponible, réessaie dans un instant.") from None
        if position is None:
            self.add_error("address", "Adresse introuvable.")
        else:
            lat, lon = position
            self.instance.location = Point(lon, lat, srid=4326)
        return cleaned


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    form = AddressAdminForm
    list_display = ["name", "first_names", "address", "zip_code", "city", "status", "organization", "disabled_at"]
    list_filter = ["status", "organization", ("disabled_at", admin.EmptyFieldListFilter)]
    search_fields = ["name", "address", "city", "zip_code"]
    raw_id_fields = ["visit_planned_by"]
    readonly_fields = ["position", "source_key"]

    def get_queryset(self, request):
        return Address.all_objects.all()  # disabled addresses included

    @admin.display(description="position (calculée depuis l'adresse)")
    def position(self, obj):
        if not obj.pk or not obj.location:
            return "Calculée à l'enregistrement."
        return format_html(
            '{:.6f}, {:.6f} — <a href="https://www.openstreetmap.org/?mlat={}&mlon={}#map=18/{}/{}" target="_blank" rel="noopener">voir sur la carte</a>',
            obj.lat, obj.lon, obj.lat, obj.lon, obj.lat, obj.lon,
        )


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    """Imported from the official electoral map (menu « Zones » of the app): read-only here."""

    list_display = ["name", "code", "organization", "score", "election"]
    list_filter = ["organization"]
    search_fields = ["name", "code"]
    exclude = ["geometry", "geometry_simple", "label_point"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class TourStopInline(admin.TabularInline):
    model = TourStop
    raw_id_fields = ["address"]
    extra = 0


@admin.register(Tour)
class TourAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "kind", "status", "area", "created_at", "started_at", "ended_at"]
    list_filter = ["status", "kind", "organization"]
    inlines = [TourStopInline]
    raw_id_fields = ["user", "area"]
    exclude = ["start_point", "end_point", "route"]


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = ["address", "user", "result", "tour", "created_at"]
    list_filter = ["result"]
    raw_id_fields = ["address", "user", "tour", "stop"]
