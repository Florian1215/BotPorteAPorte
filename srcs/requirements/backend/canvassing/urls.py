from django.urls import path

from . import views

urlpatterns = [
    path("tours/", views.TourListView.as_view()),
    path("tours/current/", views.CurrentTourView.as_view()),
    path("tours/<int:pk>/", views.TourDetailView.as_view()),
    path("tours/<int:pk>/start/", views.TourStartView.as_view()),
    path("tours/<int:pk>/finish/", views.TourFinishView.as_view()),
    path("tours/<int:pk>/stops/<int:stop_id>/result/", views.StopResultView.as_view()),
    path("areas/", views.AreaListView.as_view()),
    path("addresses/nearby/", views.NearbyAddressesView.as_view()),
    path("manual/geocode/", views.ManualGeocodeView.as_view()),
    path("manual/search/", views.ManualSearchView.as_view()),
    path("manual/mark/", views.ManualMarkView.as_view()),
    path("stats/me/", views.MyStatsView.as_view()),
    path("stats/scope/", views.ScopeOverviewView.as_view()),
]
