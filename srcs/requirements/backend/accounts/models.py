from django.contrib.auth.models import AbstractUser
from django.db import models


class Scope(models.Model):
    """A canvassing perimeter: one voter list handed over by a consulate (e.g. LEC_BERLIN_2024).

    Replaces the per-bot RLS scope of the Telegram bot: every address, area and tour belongs to one scope,
    and a militant only ever sees the data of their own scope.
    """

    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    country_code = models.CharField(
        max_length=2, default="DE", help_text="Code pays ISO 3166-1 alpha-2, utilisé pour le géocodage."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "périmètre"

    def __str__(self) -> str:
        return self.name


class User(AbstractUser):
    """A militant. Accounts must be approved by a coordinator before they can canvass
    (replaces the Google Sheet whitelist of the bot)."""

    scope = models.ForeignKey(
        Scope, null=True, blank=True, on_delete=models.SET_NULL, related_name="members", verbose_name="périmètre"
    )
    is_approved = models.BooleanField("compte validé", default=False)

    @property
    def can_canvass(self) -> bool:
        return (self.is_approved or self.is_superuser) and self.scope_id is not None
