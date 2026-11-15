from django.urls import path

from . import views

urlpatterns = [
    path("tours/", views.TourListView.as_view()),
    path("tours/current/", views.CurrentTourView.as_view()),
    path("tours/free/preview/", views.FreeTourPreviewView.as_view()),
    path("tours/<int:pk>/", views.TourDetailView.as_view()),
    path("tours/<int:pk>/start/", views.TourStartView.as_view()),
    path("tours/<int:pk>/finish/", views.TourFinishView.as_view()),
    path("tours/<int:pk>/stops/<int:stop_id>/result/", views.StopResultView.as_view()),
    path("tours/<int:pk>/results/", views.StopsResultView.as_view()),
    path("areas/", views.AreaListView.as_view()),
    path("manage/districts/", views.ManageDistrictListView.as_view()),
    path("manage/districts/<int:pk>/", views.ManageDistrictDetailView.as_view()),
    path("manage/districts/import/", views.DistrictImportView.as_view()),
    path("manage/districts/import/inspect/", views.DistrictImportInspectView.as_view()),
    path("manage/districts/import/<int:pk>/start/", views.DistrictImportStartView.as_view()),
    path("manage/score-weights/", views.ScoreWeightsView.as_view()),
    path("site/elections/", views.SiteElectionListView.as_view()),
    path("site/elections/<int:pk>/", views.SiteElectionDetailView.as_view()),
    path("site/elections/<int:pk>/activate/", views.SiteElectionActivateView.as_view()),
    path("addresses/nearby/", views.NearbyAddressesView.as_view()),
    path("stats/me/", views.MyStatsView.as_view()),
    path("stats/leaderboard/", views.LeaderboardView.as_view()),
    path("stats/organization/", views.OrganizationOverviewView.as_view()),
]
