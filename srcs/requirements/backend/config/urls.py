from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Porte-à-porte — administration"
admin.site.site_title = "Porte-à-porte"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/", include("canvassing.urls")),
]
