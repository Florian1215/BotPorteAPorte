from django.urls import path

from . import manage_views as views

urlpatterns = [
    path("members/", views.MemberListView.as_view()),
    path("members/<int:pk>/", views.MemberDetailView.as_view()),
    path("cities/", views.CitySearchView.as_view()),
    path("organizations/", views.OrganizationAdminListView.as_view()),
    path("organizations/<slug:code>/", views.OrganizationAdminDetailView.as_view()),
    path("organizations/<slug:code>/logo/", views.OrganizationLogoUploadView.as_view()),
    path("organizations/<slug:code>/enter/", views.EnterOrganizationView.as_view()),
    path("organizations/<slug:code>/addresses/", views.OrganizationAddressesView.as_view()),
    path("organizations/<slug:code>/addresses/import/", views.OrganizationAddressImportView.as_view()),
]
