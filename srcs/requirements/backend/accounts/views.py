from datetime import timedelta

from django.conf import settings
from django.contrib.auth import login, logout
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from config.settings import DEBUG
from .emails import send_email_change_code, send_email_changed_notice, send_login_code, send_sign_up_request
from .models import LoginCode, Organization, User
from .serializers import (
    EmailChangeCodeSerializer,
    EmailChangeRequestSerializer,
    LoginCodeSerializer,
    LoginLinkSerializer,
    LoginRequestSerializer,
    MeSerializer,
    OrganizationSerializer,
    ProfileSerializer,
)

INVALID_CODE = "Code incorrect ou expiré. Vérifie le dernier email reçu ou demande un nouveau code."
INVALID_LINK = "Ce lien de connexion a expiré ou a déjà été utilisé. Demande un nouveau code."


def error(message: str, code: int = status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"detail": message}, status=code)


def login_refusal(email: str, organization: Organization | None) -> str | None:
    """Why this email cannot log into this organization (None = it can)."""
    user = User.objects.filter(email=email).first()
    if user is not None and not user.is_active:
        return "Ce compte est désactivé."
    if user is not None and user.is_site_admin:
        return None
    if organization is None:
        return "Choisis ton organisation."
    if user is not None and user.organization_id and user.organization_id != organization.id:
        return "Cette adresse email est rattachée à une autre organisation."
    return None


def complete_login(request, login_code: LoginCode) -> Response:
    """The email is verified: log in, creating the account (pending approval) on first login."""
    email, organization = login_code.email, login_code.organization
    refusal = login_refusal(email, organization)
    if refusal:
        return error(refusal, status.HTTP_403_FORBIDDEN)

    user = User.objects.filter(email=email).first()
    new_sign_up = False
    if user is None:
        user = User.objects.create_user(email, organization=organization, is_approved=False)
        new_sign_up = True
    elif user.is_site_admin:
        # Site admins can work in any organization: the one picked at login becomes their current one.
        if organization and user.organization_id != organization.id:
            user.organization = organization
            user.save(update_fields=["organization"])
    elif user.organization_id is None:
        user.organization = organization
        user.is_approved = False
        user.suspended_at = None  # a new organization: a new sign-up to validate there
        user.save(update_fields=["organization", "is_approved", "suspended_at"])
        new_sign_up = True

    if new_sign_up:
        send_sign_up_request(request, user, organization)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return Response(MeSerializer(user).data)


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"detail": "ok"})


class LoginRequestView(APIView):
    """Step 1: organization + email → a code (and a link) is sent by email."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        serializer = LoginRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        organization = serializer.validated_data.get("organization")

        refusal = login_refusal(email, organization)
        if refusal:
            return error(refusal)
        recent = LoginCode.objects.filter(
            email=email, purpose=LoginCode.Purpose.LOGIN, created_at__gte=timezone.now() - timedelta(hours=1)
        ).count()
        if recent >= settings.LOGIN_CODE_MAX_PER_HOUR:
            return error("Trop de codes demandés pour cette adresse. Réessaie dans une heure.", status.HTTP_429_TOO_MANY_REQUESTS)

        _, code, token = LoginCode.issue(email, organization)
        print("code", code, flush=True)
        try:
            send_login_code(request, email, code, token, organization)
        except Exception:  # SMTP down, wrong credentials…
            return error("L'email n'a pas pu être envoyé. Réessaie dans un instant.", status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"email": email, "expires_in_minutes": settings.LOGIN_CODE_TTL_MINUTES})


class LoginCodeView(APIView):
    """Step 2a: the code typed by the militant."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        serializer = LoginCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        login_code = LoginCode.consume_code(serializer.validated_data["email"], serializer.validated_data["code"])
        if login_code is None:
            return error(INVALID_CODE)
        return complete_login(request, login_code)


class LoginLinkView(APIView):
    """Step 2b: the link of the email was clicked."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        serializer = LoginLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        login_code = LoginCode.consume_token(serializer.validated_data["token"])
        if login_code is None:
            return error(INVALID_LINK)
        return complete_login(request, login_code)


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    def get(self, request):
        return Response(MeSerializer(request.user).data)

    def patch(self, request):
        """The militant fills in their name (asked after the first login)."""
        serializer = ProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MeSerializer(request.user).data)

    @transaction.atomic
    def delete(self, request):
        """Delete my account: personal data erased, my tours and doors knocked stay in the statistics."""
        user = request.user
        if user.is_superuser:
            return error(
                "Le compte administrateur principal est défini dans la configuration du serveur "
                "(DJANGO_SUPERUSER_EMAIL) et ne peut pas être supprimé ici.",
                status.HTTP_409_CONFLICT,
            )
        user.anonymize()
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- email change


def apply_email_change(request, login_code: LoginCode) -> Response:
    user, new_email = login_code.user, login_code.email
    if user is None or not user.is_active:
        return error(INVALID_LINK)
    if User.objects.filter(email=new_email).exclude(pk=user.pk).exists():
        return error("Cette adresse est déjà utilisée par un autre compte.", status.HTTP_409_CONFLICT)
    old_email = user.email
    user.email = new_email
    user.save(update_fields=["email"])
    try:
        send_email_changed_notice(request, old_email, new_email)
    except Exception:
        pass  # the change is done; the notice is a courtesy
    return Response(MeSerializer(user).data)


class EmailChangeRequestView(APIView):
    """Step 1: send a code (and a link) to the new address, to prove it belongs to the user."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        serializer = EmailChangeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        if email == request.user.email:
            return error("C'est déjà ton adresse actuelle.")
        if User.objects.filter(email=email).exists():
            return error("Cette adresse est déjà utilisée par un autre compte.", status.HTTP_409_CONFLICT)
        recent = LoginCode.objects.filter(
            user=request.user,
            purpose=LoginCode.Purpose.EMAIL_CHANGE,
            created_at__gte=timezone.now() - timedelta(hours=1),
        ).count()
        if recent >= settings.LOGIN_CODE_MAX_PER_HOUR:
            return error("Trop de codes demandés. Réessaie dans une heure.", status.HTTP_429_TOO_MANY_REQUESTS)

        _, code, token = LoginCode.issue(email, purpose=LoginCode.Purpose.EMAIL_CHANGE, user=request.user)
        try:
            send_email_change_code(request, email, code, token)
        except Exception:
            return error("L'email n'a pas pu être envoyé. Réessaie dans un instant.", status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"email": email, "expires_in_minutes": settings.LOGIN_CODE_TTL_MINUTES})


class EmailChangeCodeView(APIView):
    """Step 2a: the code received on the new address, typed in the account screen."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        serializer = EmailChangeCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        login_code = LoginCode.consume_email_change_code(request.user, serializer.validated_data["code"])
        if login_code is None:
            return error(INVALID_CODE)
        return apply_email_change(request, login_code)


class EmailChangeLinkView(APIView):
    """Step 2b: the link of the email (works from any device: the token proves both the request and the mailbox)."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        serializer = LoginLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        login_code = LoginCode.consume_token(serializer.validated_data["token"], purpose=LoginCode.Purpose.EMAIL_CHANGE)
        if login_code is None:
            return error(INVALID_LINK)
        return apply_email_change(request, login_code)


class OrganizationListView(APIView):
    """Public list shown on the login screen."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response(OrganizationSerializer(Organization.objects.all(), many=True).data)


class OrganizationLogoView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, code):
        organization = get_object_or_404(Organization, code=code)
        if not organization.logo:
            raise Http404
        response = HttpResponse(bytes(organization.logo), content_type=organization.logo_content_type)
        response["Cache-Control"] = "public, max-age=31536000, immutable"  # the URL changes with the logo
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response
