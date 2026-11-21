from django.utils.text import slugify
from rest_framework import serializers

from .models import Organization, Role, User, VoterList, normalize_email


class OrganizationSerializer(serializers.ModelSerializer):
    logo_url = serializers.CharField(read_only=True)

    class Meta:
        model = Organization
        fields = ["code", "name", "country_code", "city", "city_lat", "city_lon", "logo_url"]


class OrganizationAdminSerializer(OrganizationSerializer):
    """Create / edit an organization.

    `code` is an internal identifier (URLs, login, `make import ORG=…`): generated from the name, never typed.
    """

    n_members = serializers.IntegerField(read_only=True, required=False)
    n_pending = serializers.IntegerField(read_only=True, required=False)
    # Voter list (LEC) the organization depends on, and how far around its city: chosen by the site admins only
    # (see `OrganizationAdminDetailView`).
    voter_list = serializers.PrimaryKeyRelatedField(queryset=VoterList.objects.all(), allow_null=True, required=False)
    voter_list_name = serializers.CharField(source="voter_list.name", read_only=True, default=None)
    radius_km = serializers.IntegerField(min_value=1, max_value=500, required=False)

    class Meta(OrganizationSerializer.Meta):
        fields = OrganizationSerializer.Meta.fields + ["n_members", "n_pending", "voter_list", "voter_list_name", "radius_km"]
        read_only_fields = ["code"]

    def create(self, validated_data):
        base = slugify(validated_data["name"])[:56] or "organisation"
        code, n = base, 2
        while Organization.objects.filter(code=code).exists():
            code, n = f"{base}-{n}", n + 1
        return super().create({**validated_data, "code": code})

    def validate_country_code(self, value: str) -> str:
        if len(value) != 2 or not value.isalpha():
            raise serializers.ValidationError("Code pays à 2 lettres (ex. DE, BE, GB).")
        return value.upper()

    def validate(self, attrs):
        # The city comes from the search: name, coordinates and country together.
        city_fields = {"city", "city_lat", "city_lon", "country_code"}
        if city_fields & set(attrs):
            missing = [f for f in sorted(city_fields) if attrs.get(f) in (None, "")]
            if missing:
                raise serializers.ValidationError({"city": "Choisis la ville dans la liste des résultats."})
        if self.instance is None and not attrs.get("city"):
            raise serializers.ValidationError({"city": "Choisis la ville de l'organisation."})
        if self.instance is None and not attrs.get("voter_list"):
            raise serializers.ValidationError({"voter_list": "Choisis la LEC dont dépend l'organisation."})
        return attrs


class VoterListSerializer(serializers.ModelSerializer):
    """A voter list (LEC), for the site admins: with its address counts and the organizations depending on it."""

    n_active = serializers.IntegerField(read_only=True, required=False)
    n_disabled = serializers.IntegerField(read_only=True, required=False)
    organizations = serializers.SerializerMethodField()

    class Meta:
        model = VoterList
        fields = ["id", "name", "country_code", "created_at", "n_active", "n_disabled", "organizations"]
        read_only_fields = ["id", "created_at"]

    def get_organizations(self, voter_list) -> list[dict]:
        return [{"code": o.code, "name": o.name, "city": o.city} for o in voter_list.organizations.all()]

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Donne un nom à la LEC (ex. LEC Berlin).")
        return value

    def validate_country_code(self, value: str) -> str:
        if len(value) != 2 or not value.isalpha():
            raise serializers.ValidationError("Code pays à 2 lettres (ex. DE, BE, GB).")
        return value.upper()



class MeSerializer(serializers.ModelSerializer):
    organization = OrganizationSerializer(read_only=True)
    role = serializers.CharField(source="effective_role", read_only=True)
    can_canvass = serializers.BooleanField(read_only=True)
    can_validate = serializers.BooleanField(read_only=True)
    can_manage_organization = serializers.BooleanField(read_only=True)
    is_site_admin = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "is_approved",
            "suspended_at",
            "is_staff",
            "role",
            "can_canvass",
            "can_validate",
            "can_manage_organization",
            "is_site_admin",
            "organization",
            "telegram_id",
            "navigation_app",
            "route_display",
        ]
        read_only_fields = ["telegram_id"]


class ProfileSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(max_length=150)

    class Meta:
        model = User
        fields = ["first_name", "last_name", "navigation_app", "route_display"]


class MemberSerializer(serializers.ModelSerializer):
    role = serializers.CharField(source="effective_role", read_only=True)
    organization = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "email", "first_name", "last_name", "role", "is_approved", "suspended_at", "organization", "date_joined", "last_login",
        ]


class MemberCreateSerializer(serializers.Serializer):
    """A validator adds an email beforehand: that person is approved as soon as they log in."""

    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    role = serializers.ChoiceField(choices=Role.choices, default=Role.MILITANT)
    organization = serializers.SlugRelatedField(slug_field="code", queryset=Organization.objects.all(), required=False)
    send_invitation = serializers.BooleanField(default=True)

    def validate_email(self, value: str) -> str:
        return normalize_email(value)


class MemberUpdateSerializer(serializers.Serializer):
    """Validators / responsables change the role or access; name and email belong to the member (Mon compte)."""

    role = serializers.ChoiceField(choices=Role.choices, required=False)
    is_approved = serializers.BooleanField(required=False)


class LoginRequestSerializer(serializers.Serializer):
    organization = serializers.SlugRelatedField(
        slug_field="code", queryset=Organization.objects.all(), required=False, allow_null=True
    )
    email = serializers.EmailField()

    def validate_email(self, value: str) -> str:
        return normalize_email(value)


class LoginCodeSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(max_length=16)

    def validate_email(self, value: str) -> str:
        return normalize_email(value)


class LoginLinkSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=128)


class EmailChangeRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value: str) -> str:
        return normalize_email(value)


class EmailChangeCodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=16)
