import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone
from django.utils.crypto import salted_hmac


class Organization(models.Model):
    """A local unit (groupe d'action) running its own canvassing: its own voter list, areas, tours and members.

    Replaces the per-bot RLS scope of the Telegram bot: every address, area and tour belongs to one organization,
    and a militant only ever sees the data of their own organization.
    """

    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField("nom", max_length=128)
    # City of the organization (picked from a search): default map position, and country for geocoding.
    city = models.CharField("ville", max_length=128, blank=True, default="")
    city_lat = models.FloatField(null=True, blank=True)
    city_lon = models.FloatField(null=True, blank=True)
    country_code = models.CharField(
        "pays", max_length=2, default="DE", help_text="Code pays ISO 3166-1 alpha-2 (déduit de la ville), pour le géocodage."
    )
    # Logo stored in the database (small image) and served by /api/auth/organizations/<code>/logo/:
    # no media volume to share between containers.
    # Weight of each criterion in the score of the polling districts (see canvassing/services/scoring.py).
    score_weights = models.JSONField("pondération du score", default=dict, blank=True)
    logo = models.BinaryField(null=True, blank=True, editable=False)
    logo_content_type = models.CharField(max_length=32, blank=True, default="", editable=False)
    logo_updated_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "organisation"

    def __str__(self) -> str:
        return self.name

    @property
    def logo_url(self) -> str | None:
        if not self.logo_updated_at:
            return None
        return f"/api/auth/organizations/{self.code}/logo/?v={int(self.logo_updated_at.timestamp())}"


class Role(models.TextChoices):
    MILITANT = "militant", "Militant·e"
    EXPERIENCED = "experienced", "Militant·e aguerri·e"
    MANAGER = "manager", "Responsable d'organisation"
    ADMIN = "admin", "Administrateur·rice du site"


ROLE_RANK = {Role.MILITANT: 0, Role.EXPERIENCED: 1, Role.MANAGER: 2, Role.ADMIN: 3}


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


class UserManager(BaseUserManager):
    """Accounts are identified by their email; there are no passwords (login codes sent by email)."""

    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("L'adresse email est obligatoire.")
        user = self.model(email=normalize_email(email), **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.update(is_staff=True, is_superuser=True, is_approved=True, role=Role.ADMIN)
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    """A militant, identified by their email (login with a one-time code, no password).

    Accounts must be approved (by an experienced militant, a manager or an admin) before they can canvass,
    unless their email was added beforehand by one of them.
    Site admins are not tied to one organization: `organization` is the one they picked when logging in.
    """

    username = None
    email = models.EmailField("adresse email", unique=True)

    organization = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="members",
        verbose_name="organisation",
    )
    role = models.CharField("rôle", max_length=16, choices=Role.choices, default=Role.MILITANT)
    is_approved = models.BooleanField("compte validé", default=False)
    # Suspended by a responsable (not approved any more, but not a sign-up to validate either).
    suspended_at = models.DateTimeField("suspendu·e le", null=True, blank=True)

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        verbose_name = "membre"
        ordering = ["first_name", "email"]

    def __str__(self) -> str:
        return f"{self.first_name} <{self.email}>" if self.first_name else self.email

    def save(self, *args, **kwargs):
        self.email = normalize_email(self.email)
        super().save(*args, **kwargs)

    @property
    def display_name(self) -> str:
        return " ".join(filter(None, [self.first_name, self.last_name])) or self.email

    @property
    def is_site_admin(self) -> bool:
        return self.is_superuser or self.role == Role.ADMIN

    @property
    def effective_role(self) -> str:
        return Role.ADMIN if self.is_site_admin else self.role

    def has_role(self, minimum: str) -> bool:
        return ROLE_RANK[Role(self.effective_role)] >= ROLE_RANK[Role(minimum)]

    @property
    def is_active_member(self) -> bool:
        return self.is_approved or self.is_site_admin

    @property
    def can_canvass(self) -> bool:
        return self.is_active_member and self.organization_id is not None

    @property
    def can_validate(self) -> bool:
        """Approve / reject sign-up requests of their organization."""
        return self.can_canvass and self.has_role(Role.EXPERIENCED)

    @property
    def can_manage_organization(self) -> bool:
        """Manage every member of their organization and its name / logo."""
        return self.can_canvass and self.has_role(Role.MANAGER)

    def anonymize(self) -> None:
        """Account deleted by its owner: personal data erased, tours and doors knocked kept (statistics).

        The row stays (tours and visits point to it) but cannot log in any more and is listed nowhere;
        the email is freed, so the person can sign up again later.
        """
        from canvassing.models import Tour  # avoid an import cycle
        from canvassing.services.tours import finish_tour

        for tour in Tour.objects.filter(user=self, status=Tour.TourStatus.ACTIVE):
            finish_tour(tour)  # releases the addresses still reserved
        Tour.objects.filter(user=self, status=Tour.TourStatus.DRAFT).delete()
        LoginCode.objects.filter(models.Q(user=self) | models.Q(email=self.email)).delete()

        self.email = f"compte-supprime-{self.pk}@supprime.invalid"
        self.first_name = ""
        self.last_name = ""
        self.set_unusable_password()
        self.is_active = False
        self.is_approved = False
        self.suspended_at = None
        self.is_staff = False
        self.role = Role.MILITANT
        self.save()

    def can_manage_member(self, other: "User") -> bool:
        """Change role / suspend `other` (never oneself, never someone of a higher rank)."""
        if other.pk == self.pk or not self.is_active_member:
            return False
        if self.is_site_admin:
            return True
        return (
            self.has_role(Role.MANAGER)
            and other.organization_id == self.organization_id
            and not other.is_site_admin
        )

    def can_validate_member(self, other: "User") -> bool:
        if other.pk == self.pk or not self.is_active_member:
            return False
        if self.is_site_admin:
            return True
        return self.has_role(Role.EXPERIENCED) and other.organization_id == self.organization_id


def _digest(kind: str, value: str) -> str:
    return salted_hmac(f"accounts.login-code.{kind}", value, algorithm="sha256").hexdigest()


class LoginCode(models.Model):
    """One-time code (6 digits to type) + token (for the link in the same email), proving access to a mailbox.

    Used to log in, and to confirm a new email address (`purpose`). A code only ever works for its own purpose.
    Only hashes are stored. A code is valid `LOGIN_CODE_TTL_MINUTES`, can be used once, and is locked
    after `LOGIN_CODE_MAX_ATTEMPTS` wrong guesses.
    """

    class Purpose(models.TextChoices):
        LOGIN = "login", "Connexion"
        EMAIL_CHANGE = "email_change", "Changement d'email"

    email = models.EmailField()
    purpose = models.CharField(max_length=16, choices=Purpose.choices, default=Purpose.LOGIN)
    # Email change: the account whose address becomes `email` once confirmed.
    user = models.ForeignKey("User", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    organization = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    code_hash = models.CharField(max_length=64)
    token_hash = models.CharField(max_length=64, unique=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["email", "created_at"])]

    @classmethod
    def issue(
        cls,
        email: str,
        organization: Organization | None = None,
        purpose: str = Purpose.LOGIN,
        user: "User | None" = None,
    ) -> tuple["LoginCode", str, str]:
        """Create a code; returns (instance, code, token). Previous unused codes for the same thing are revoked."""
        email = normalize_email(email)
        now = timezone.now()
        previous = cls.objects.filter(purpose=purpose, used_at__isnull=True)
        previous = previous.filter(user=user) if purpose == cls.Purpose.EMAIL_CHANGE else previous.filter(email=email)
        previous.update(used_at=now)
        code = f"{secrets.randbelow(1_000_000):06d}"
        token = secrets.token_urlsafe(32)
        instance = cls.objects.create(
            email=email,
            purpose=purpose,
            user=user,
            organization=organization,
            code_hash=_digest("code", f"{email}:{code}"),
            token_hash=_digest("token", token),
            expires_at=now + timedelta(minutes=settings.LOGIN_CODE_TTL_MINUTES),
        )
        return instance, code, token

    @property
    def is_usable(self) -> bool:
        return (
            self.used_at is None
            and self.expires_at > timezone.now()
            and self.attempts < settings.LOGIN_CODE_MAX_ATTEMPTS
        )

    def _check(self, code: str) -> bool:
        """Compare `code`; counts the wrong guesses and marks the code used when it matches."""
        if not self.is_usable:
            return False
        if not hmac.compare_digest(self.code_hash, _digest("code", f"{self.email}:{code.strip().replace(' ', '')}")):
            self.attempts += 1
            self.save(update_fields=["attempts"])
            return False
        self.used_at = timezone.now()
        self.save(update_fields=["used_at"])
        return True

    @classmethod
    def consume_code(cls, email: str, code: str) -> "LoginCode | None":
        """Login code typed for `email`."""
        instance = (
            cls.objects.filter(email=normalize_email(email), purpose=cls.Purpose.LOGIN, used_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        return instance if instance is not None and instance._check(code) else None

    @classmethod
    def consume_email_change_code(cls, user: "User", code: str) -> "LoginCode | None":
        """Code received on the new address, typed by the logged-in `user`."""
        instance = (
            cls.objects.filter(user=user, purpose=cls.Purpose.EMAIL_CHANGE, used_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        return instance if instance is not None and instance._check(code) else None

    @classmethod
    def consume_token(cls, token: str, purpose: str = Purpose.LOGIN) -> "LoginCode | None":
        instance = cls.objects.filter(token_hash=_digest("token", token), purpose=purpose).first()
        if instance is None or not instance.is_usable:
            return None
        instance.used_at = timezone.now()
        instance.save(update_fields=["used_at"])
        return instance
