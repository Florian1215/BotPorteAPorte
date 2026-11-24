from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from .map_tiles import tile_config

admin.site.site_header = "Porte-à-porte — administration"
admin.site.site_title = "Porte-à-porte"


def public_config(request):
    """Runtime settings the frontend needs (no rebuild when they change)."""
    return JsonResponse(
        {
            "map": tile_config(),
        }
    )


urlpatterns = [
    path("api/config/", public_config),
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/manage/", include("accounts.manage_urls")),
    path("api/", include("canvassing.urls")),
]
