from django.urls import path

from . import manage_views as views

urlpatterns = [
    path("members/", views.MemberListView.as_view()),
    path("members/<int:pk>/", views.MemberDetailView.as_view()),
    path("cities/", views.CitySearchView.as_view()),
    path("organizations/", views.OrganizationAdminListView.as_view()),
    path("organizations/<slug:code>/", views.OrganizationAdminDetailView.as_view()),
    path("organizations/<slug:code>/enter/", views.EnterOrganizationView.as_view()),
    path("voter-lists/", views.VoterListListView.as_view()),
    path("voter-lists/<int:pk>/", views.VoterListDetailView.as_view()),
    path("voter-lists/<int:pk>/addresses/", views.VoterListAddressesView.as_view()),
    path("voter-lists/<int:pk>/addresses/import/", views.VoterListImportView.as_view()),
]
