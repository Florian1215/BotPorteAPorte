from django.urls import path

from . import views

urlpatterns = [
    path("csrf/", views.CsrfView.as_view()),
    path("login/request/", views.LoginRequestView.as_view()),
    path("login/code/", views.LoginCodeView.as_view()),
    path("login/link/", views.LoginLinkView.as_view()),
    path("logout/", views.LogoutView.as_view()),
    path("me/", views.MeView.as_view()),
    path("me/email/", views.EmailChangeRequestView.as_view()),
    path("me/telegram/", views.TelegramLinkView.as_view()),
    path("me/email/code/", views.EmailChangeCodeView.as_view()),
    path("me/email/link/", views.EmailChangeLinkView.as_view()),
    path("organizations/", views.OrganizationListView.as_view()),
    path("organizations/<slug:code>/logo/", views.OrganizationLogoView.as_view()),
]
