from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .models import Address, Area, Tour, TourStop, Visit


@admin.register(Address)
class AddressAdmin(GISModelAdmin):
    list_display = ["name", "first_names", "address", "zip_code", "city", "status", "scope", "visit_planned_by"]
    list_filter = ["status", "scope"]
    search_fields = ["name", "address", "city", "zip_code"]
    raw_id_fields = ["visit_planned_by"]


@admin.register(Area)
class AreaAdmin(GISModelAdmin):
    list_display = ["name", "scope", "score", "status"]
    list_filter = ["scope"]
    search_fields = ["name"]
    raw_id_fields = ["visit_planned_by"]


class TourStopInline(admin.TabularInline):
    model = TourStop
    raw_id_fields = ["address"]
    extra = 0


@admin.register(Tour)
class TourAdmin(GISModelAdmin):
    list_display = ["id", "user", "kind", "status", "area", "created_at", "started_at", "ended_at"]
    list_filter = ["status", "kind", "scope"]
    inlines = [TourStopInline]
    raw_id_fields = ["user", "area"]


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = ["address", "user", "result", "tour", "created_at"]
    list_filter = ["result"]
    raw_id_fields = ["address", "user", "tour", "stop"]
