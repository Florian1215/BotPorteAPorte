"""Management screens: sign-up validation, members, organizations (name, logo).

Who can do what:
- militant·e aguerri·e: approve / reject the sign-ups of their organization;
- responsable d'organisation: every right on their organization (members, roles, name, logo);
- administrateur·rice du site: every right on every organization, creates organizations.
"""
from datetime import timedelta

import requests
from django.conf import settings
from django.core.cache import cache

from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from canvassing.models import Address, AddressImport
from canvassing.services import address_import

from .emails import send_invitation
from .images import InvalidImage, process_logo
from .models import ROLE_RANK, LoginCode, Organization, Role, User
from .permissions import CanValidate, IsSiteAdmin
from .serializers import (
    MemberCreateSerializer,
    MemberSerializer,
    MemberUpdateSerializer,
    MeSerializer,
    OrganizationAdminSerializer,
)

# Upload size only bounded by nginx (20 MB): the image is resized server-side anyway.
LOGO_MAX_BYTES = 20 * 1024 * 1024


def with_counts(queryset):
    active = Q(members__is_active=True)
    # Admins attached to the organization count as members (they are listed with them).
    is_admin = Q(members__role=Role.ADMIN) | Q(members__is_superuser=True)
    return queryset.annotate(
        n_members=Count("members", filter=active & (Q(members__is_approved=True) | is_admin)),
        n_pending=Count(
            "members", filter=active & ~is_admin & Q(members__is_approved=False, members__suspended_at__isnull=True)
        ),
    )


def managed_organization(request, code: str) -> Organization:
    """The organization `code`, if the user may manage it (its responsable, or a site admin)."""
    organization = get_object_or_404(with_counts(Organization.objects.all()), code=code)
    user = request.user
    if user.is_site_admin or (user.can_manage_organization and user.organization_id == organization.id):
        return organization
    raise PermissionDenied("Tu ne peux gérer que ta propre organisation.")


# --------------------------------------------------------------------------- members


class MemberListView(APIView):
    permission_classes = [CanValidate]

    def get(self, request):
        user = request.user
        code = request.query_params.get("organization")
        if code and user.is_site_admin:
            organization = get_object_or_404(Organization, code=code)
        elif user.organization_id:
            organization = user.organization
        else:
            raise ValidationError({"organization": "Choisis une organisation."})

        pending = request.query_params.get("status", "pending") == "pending"
        if not pending and not (user.is_site_admin or user.can_manage_organization):
            raise PermissionDenied("Seul·es les responsables de l'organisation peuvent gérer les membres.")

        members = User.objects.filter(organization=organization, is_active=True)
        # Suspended members stay in the members list (to reactivate them), not in the sign-ups to validate.
        if pending:
            members = members.filter(is_approved=False, suspended_at__isnull=True)
        else:
            members = members.filter(Q(is_approved=True) | Q(suspended_at__isnull=False))
        if not user.is_site_admin:  # site admins only "visit" organizations: they are not listed as members
            members = members.exclude(role=Role.ADMIN).exclude(is_superuser=True)
        members = members.order_by("-date_joined" if pending else "first_name", "email")
        return Response(MemberSerializer(members, many=True).data)

    def post(self, request):
        """Add an email beforehand: the person is approved and can canvass as soon as they log in."""
        me = request.user
        serializer = MemberCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        organization = data.get("organization") if me.is_site_admin else None
        organization = organization or me.organization
        if organization is None:
            raise ValidationError({"organization": "Choisis une organisation."})
        if data["role"] != Role.MILITANT and not (me.is_site_admin or me.can_manage_organization):
            raise PermissionDenied("Seul·es les responsables de l'organisation peuvent attribuer un rôle.")
        if ROLE_RANK[Role(data["role"])] > ROLE_RANK[Role(me.effective_role)]:
            raise PermissionDenied("Tu ne peux pas donner un rôle supérieur au tien.")

        member = User.objects.filter(email=data["email"]).first()
        if member is not None:
            if member.organization_id != organization.id:
                return Response(
                    {"detail": "Cette adresse a déjà un compte dans une autre organisation."}, status=status.HTTP_409_CONFLICT
                )
            if member.is_approved:
                return Response({"detail": "Cette personne est déjà membre."}, status=status.HTTP_409_CONFLICT)
            # Already signed up and waiting: adding them is approving them.
            member.is_approved = True
            member.role = data["role"]
            member.first_name = member.first_name or data["first_name"]
            member.last_name = member.last_name or data["last_name"]
            member.save()
            return Response(MemberSerializer(member).data)

        member = User.objects.create_user(
            data["email"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            organization=organization,
            role=data["role"],
            is_approved=True,
        )
        if data["send_invitation"]:
            try:
                send_invitation(
                    request, member.email, organization, invited_by=me.display_name,
                    role_label=Role(data["role"]).label if data["role"] != Role.MILITANT else None,
                )
            except Exception:
                pass  # the account exists; they can still log in from the site
        return Response(MemberSerializer(member).data, status=status.HTTP_201_CREATED)


class MemberDetailView(APIView):
    permission_classes = [CanValidate]

    def get_member(self, request, pk) -> User:
        member = get_object_or_404(User, pk=pk, is_active=True)
        if not request.user.is_site_admin and member.organization_id != request.user.organization_id:
            raise PermissionDenied("Ce compte n'appartient pas à ton organisation.")
        if member.is_superuser and not request.user.is_superuser:
            raise PermissionDenied("Ce compte ne peut pas être modifié.")
        return member

    def patch(self, request, pk):
        """Approve a sign-up, suspend a member or change their role."""
        me = request.user
        member = self.get_member(request, pk)
        serializer = MemberUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        approving = data.get("is_approved") is True and not member.is_approved and member.suspended_at is None
        reactivating = data.get("is_approved") is True and member.suspended_at is not None
        other_changes = reactivating or ("role" in data and data["role"] != member.role) or (
            data.get("is_approved") is False and member.is_approved
        )
        if approving and not me.can_validate_member(member):
            raise PermissionDenied("Tu ne peux pas valider ce compte.")
        if other_changes and not me.can_manage_member(member):
            raise PermissionDenied("Seul·es les responsables de l'organisation peuvent modifier les membres.")
        if "role" in data and ROLE_RANK[Role(data["role"])] > ROLE_RANK[Role(me.effective_role)]:
            raise PermissionDenied("Tu ne peux pas donner un rôle supérieur au tien.")

        for field, value in data.items():
            setattr(member, field, value)
        if "is_approved" in data:
            member.suspended_at = None if data["is_approved"] else (member.suspended_at or timezone.now())
            data = {**data, "suspended_at": member.suspended_at}
        member.save(update_fields=list(data) or None)
        return Response(MemberSerializer(member).data)

    def delete(self, request, pk):
        """Reject a sign-up (only accounts not yet approved; approved members are suspended instead)."""
        member = self.get_member(request, pk)
        if member.is_approved or member.suspended_at or member.is_site_admin:
            return Response(
                {"detail": "Seule une inscription en attente peut être refusée. Suspends plutôt ce compte."},
                status=status.HTTP_409_CONFLICT,
            )
        if not request.user.can_validate_member(member):
            raise PermissionDenied("Tu ne peux pas refuser ce compte.")
        # Nothing is kept: the account, and the login codes sent to that address (the only other trace of the email).
        with transaction.atomic():
            LoginCode.objects.filter(email=member.email).delete()
            member.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- organizations


class OrganizationAdminListView(APIView):
    permission_classes = [IsSiteAdmin]

    def get(self, request):
        return Response(OrganizationAdminSerializer(with_counts(Organization.objects.all()), many=True).data)

    def post(self, request):
        serializer = OrganizationAdminSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        organization = serializer.save()
        return Response(OrganizationAdminSerializer(organization).data, status=status.HTTP_201_CREATED)


class OrganizationAdminDetailView(APIView):
    def get(self, request, code):
        return Response(OrganizationAdminSerializer(managed_organization(request, code)).data)

    def patch(self, request, code):
        organization = managed_organization(request, code)
        serializer = OrganizationAdminSerializer(organization, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(OrganizationAdminSerializer(managed_organization(request, code)).data)


class OrganizationLogoUploadView(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request, code):
        organization = managed_organization(request, code)
        upload = request.FILES.get("logo")
        if upload is None:
            raise ValidationError({"logo": "Choisis une image."})
        if upload.size > LOGO_MAX_BYTES:
            raise ValidationError({"logo": "Image trop lourde (20 Mo maximum)."})
        try:
            data = process_logo(upload)
        except InvalidImage as exc:
            raise ValidationError({"logo": str(exc)}) from None
        organization.logo = data
        organization.logo_content_type = "image/webp"
        organization.logo_updated_at = timezone.now()
        organization.save(update_fields=["logo", "logo_content_type", "logo_updated_at"])
        return Response(OrganizationAdminSerializer(organization).data)

    def delete(self, request, code):
        organization = managed_organization(request, code)
        organization.logo = None
        organization.logo_content_type = ""
        organization.logo_updated_at = None
        organization.save(update_fields=["logo", "logo_content_type", "logo_updated_at"])
        return Response(OrganizationAdminSerializer(organization).data)


# --------------------------------------------------------------------------- voter list


IMPORT_MAX_BYTES = 20 * 1024 * 1024


class OrganizationAddressesView(APIView):
    def get(self, request, code):
        organization = managed_organization(request, code)
        counts = Address.all_objects.filter(organization=organization).aggregate(
            active=Count("id", filter=Q(disabled_at__isnull=True)),
            disabled=Count("id", filter=Q(disabled_at__isnull=False)),
        )
        return Response(counts)


STALE_IMPORT = timedelta(hours=6)


def address_import_to_dict(job: AddressImport | None) -> dict | None:
    if job is None:
        return None
    return {
        "id": job.id,
        "filename": job.filename,
        "status": job.status,
        "message": job.message,
        "report": job.report,
        "geocode_total": job.geocode_total,
        "geocode_done": job.geocode_done,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }


def last_address_import(organization) -> AddressImport | None:
    job = AddressImport.objects.filter(organization=organization).first()
    if job and job.status == AddressImport.ImportStatus.RUNNING and timezone.now() - job.created_at > STALE_IMPORT:
        job.status = AddressImport.ImportStatus.FAILED
        job.message = "L'import a été interrompu (redémarrage du serveur ?). Relance-le : les adresses déjà géocodées ne le seront pas une deuxième fois."
        AddressImport.objects.filter(pk=job.pk).update(status=job.status, message=job.message)
    return job


class OrganizationAddressImportView(APIView):
    """Import the voter list: the consular list (.xls / .xlsx) or a JSON file.

    POST `dry_run=1`: what would change (shown before confirming). POST: start the import in the background
    (the addresses have to be geocoded). GET: the last import, polled while it runs.
    """

    parser_classes = [MultiPartParser]

    def get(self, request, code):
        return Response(address_import_to_dict(last_address_import(managed_organization(request, code))))

    def post(self, request, code):
        organization = managed_organization(request, code)
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "Choisis la liste électorale (.xls ou .xlsx)."})
        if upload.size > IMPORT_MAX_BYTES:
            raise ValidationError({"file": "Le fichier ne doit pas dépasser 20 Mo."})
        running = last_address_import(organization)
        if running and running.status == AddressImport.ImportStatus.RUNNING:
            raise ValidationError({"file": "Un import est déjà en cours pour cette organisation."})
        data = upload.read()
        dry_run = str(request.data.get("dry_run", "")).lower() in {"1", "true", "yes"}
        try:
            if dry_run:
                return Response({**address_import.preview(organization, data, upload.name).as_dict(), "dry_run": True})
            job = address_import.start_import(organization, request.user, data, upload.name)
        except address_import.ImportFileError as exc:
            raise ValidationError({"file": str(exc)}) from None
        return Response(address_import_to_dict(job), status=status.HTTP_202_ACCEPTED)


# --------------------------------------------------------------------------- city search

PHOTON_URL = "https://photon.komoot.io/api/"


class CitySearchView(APIView):
    """City autocomplete for the organization settings (Photon: OpenStreetMap search made for type-ahead)."""

    def get(self, request):
        user = request.user
        if not (user.is_site_admin or user.can_manage_organization):
            raise PermissionDenied("Réservé aux responsables d'organisation.")
        query = " ".join(request.query_params.get("q", "").split())[:80]
        if len(query) < 2:
            return Response([])
        cache_key = f"city-search:{query.lower()}"
        results = cache.get(cache_key)
        if results is None:
            try:
                response = requests.get(
                    PHOTON_URL,
                    params={"q": query, "limit": 8, "lang": "fr", "layer": "city"},
                    headers={"User-Agent": settings.NOMINATIM_USER_AGENT},
                    timeout=5,
                )
                response.raise_for_status()
                features = response.json().get("features", [])
            except (requests.RequestException, ValueError):
                return Response({"detail": "La recherche de villes est indisponible, réessaie."}, status=503)
            results, seen = [], set()
            for feature in features:
                props = feature.get("properties", {})
                lon, lat = feature.get("geometry", {}).get("coordinates", [None, None])
                country_code = (props.get("countrycode") or "").upper()
                name = props.get("name")
                if not name or lat is None or len(country_code) != 2:
                    continue
                key = (name, props.get("state"), country_code)
                if key in seen:
                    continue
                seen.add(key)
                results.append(
                    {
                        "name": name,
                        "region": props.get("state") or props.get("county") or "",
                        "country": props.get("country") or country_code,
                        "country_code": country_code,
                        "lat": lat,
                        "lon": lon,
                    }
                )
            cache.set(cache_key, results, 60 * 60 * 24)
        return Response(results)


class EnterOrganizationView(APIView):
    """A site admin switches to another organization (canvasses / manages it as if they had logged into it)."""

    permission_classes = [IsSiteAdmin]

    def post(self, request, code):
        request.user.organization = get_object_or_404(Organization, code=code)
        request.user.save(update_fields=["organization"])
        return Response(MeSerializer(request.user).data)
