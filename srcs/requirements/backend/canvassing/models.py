from django.conf import settings
from django.contrib.gis.db import models

from accounts.models import Scope


class Status(models.IntegerChoices):
    """Address status. Values are identical to the Telegram bot's `Status` enum."""

    TO_VISIT = 0, "À visiter"
    PLANNED = 1, "En cours de visite"
    FAILURE = 2, "Adresse introuvable"
    COMMITMENT_TO_VOTE = 4, "Promesse de vote"
    GOOD_CONVERSATION = 5, "Bonne conversation"
    DO_NOT_CONTACT = 6, "Ne plus contacter"


class VisitResult(models.TextChoices):
    """Feedback a militant gives after ringing at a door (same 5 options as the bot)."""

    COMMITMENT_TO_VOTE = "commitment_to_vote", "Promesse de vote"
    GOOD_CONVERSATION = "good_conversation", "Bonne conversation"
    DO_NOT_CONTACT = "do_not_contact", "Conversation stérile / Ne plus déranger"
    ADDRESS_TO_RETRY = "address_to_retry", "Personne absente / Repasser"
    ADDRESS_FAILURE = "address_failure", "Adresse introuvable"


RESULT_TO_STATUS = {
    VisitResult.COMMITMENT_TO_VOTE: Status.COMMITMENT_TO_VOTE,
    VisitResult.GOOD_CONVERSATION: Status.GOOD_CONVERSATION,
    VisitResult.DO_NOT_CONTACT: Status.DO_NOT_CONTACT,
    VisitResult.ADDRESS_TO_RETRY: Status.TO_VISIT,  # released so that someone can come back later
    VisitResult.ADDRESS_FAILURE: Status.FAILURE,
}

SUCCESS_RESULTS = {VisitResult.COMMITMENT_TO_VOTE, VisitResult.GOOD_CONVERSATION}


def semi_anonymize_name(name: str, show_n_first_letters: int = 3) -> str:
    if len(name) <= show_n_first_letters:
        return name
    return name[:show_n_first_letters] + "*" * (len(name) - show_n_first_letters)


class Address(models.Model):
    scope = models.ForeignKey(Scope, on_delete=models.CASCADE, related_name="addresses")
    name = models.CharField("nom d'usage (semi-anonymisé)", max_length=255)
    first_names = models.CharField("prénoms", max_length=255, blank=True)
    address = models.CharField("adresse", max_length=255)
    zip_code = models.CharField("code postal", max_length=16)
    city = models.CharField("ville", max_length=128)
    location = models.PointField(srid=4326)
    status = models.IntegerField(choices=Status.choices, default=Status.TO_VISIT, db_index=True)
    visit_planned_at = models.DateTimeField(null=True, blank=True)
    visit_planned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "adresse"
        indexes = [models.Index(fields=["scope", "status"])]

    def __str__(self) -> str:
        return f"{self.name} — {self.full_address}"

    @property
    def lat(self) -> float:
        return self.location.y

    @property
    def lon(self) -> float:
        return self.location.x

    @property
    def full_address(self) -> str:
        return f"{self.address}, {self.zip_code} {self.city}"

    @property
    def display_name(self) -> str:
        return semi_anonymize_name(self.name)

    @property
    def first_name(self) -> str:
        return self.first_names.split(" ")[0] if self.first_names else ""


class Area(models.Model):
    """A predefined canvassing area prepared by the coordinators (e.g. a polling district)."""

    scope = models.ForeignKey(Scope, on_delete=models.CASCADE, related_name="areas")
    name = models.CharField("nom", max_length=255)
    geometry = models.GeometryField(srid=4326)
    status = models.IntegerField(choices=Status.choices, default=Status.TO_VISIT)
    score = models.FloatField(default=0.0, help_text="Plus le score est élevé, plus la zone est prioritaire.")
    visit_planned_at = models.DateTimeField(null=True, blank=True)
    visit_planned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "zone"
        ordering = ["-score", "name"]

    def __str__(self) -> str:
        return self.name


class Tour(models.Model):
    class Kind(models.TextChoices):
        FREE = "free", "Tournée libre"
        PREDEFINED = "predefined", "Tournée préparée"

    class TourStatus(models.TextChoices):
        DRAFT = "draft", "Brouillon"
        ACTIVE = "active", "En cours"
        COMPLETED = "completed", "Terminée"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tours")
    scope = models.ForeignKey(Scope, on_delete=models.CASCADE, related_name="tours")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=TourStatus.choices, default=TourStatus.DRAFT, db_index=True)
    area = models.ForeignKey(Area, null=True, blank=True, on_delete=models.SET_NULL, related_name="tours")
    start_point = models.PointField(srid=4326)
    end_point = models.PointField(srid=4326, null=True, blank=True)
    radius_km = models.FloatField(null=True, blank=True)
    route = models.LineStringField(srid=4326, null=True, blank=True)
    route_distance_m = models.FloatField(null=True, blank=True)
    route_duration_s = models.FloatField(null=True, blank=True)
    route_approximate = models.BooleanField(default=False, help_text="Ligne droite (service d'itinéraire indisponible).")
    too_many_addresses = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "tournée"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} #{self.pk} ({self.user})"


class TourStop(models.Model):
    tour = models.ForeignKey(Tour, on_delete=models.CASCADE, related_name="stops")
    address = models.ForeignKey(Address, on_delete=models.CASCADE, related_name="tour_stops")
    position = models.PositiveIntegerField()
    result = models.CharField(max_length=32, choices=VisitResult.choices, blank=True, default="")
    visited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["position"]


class Visit(models.Model):
    """Log of every feedback given on an address (from a tour or entered manually). Used for statistics."""

    address = models.ForeignKey(Address, on_delete=models.CASCADE, related_name="visits")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="visits")
    tour = models.ForeignKey(Tour, null=True, blank=True, on_delete=models.SET_NULL, related_name="visits")
    stop = models.OneToOneField(TourStop, null=True, blank=True, on_delete=models.SET_NULL, related_name="visit")
    result = models.CharField(max_length=32, choices=VisitResult.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "visite"
        ordering = ["-created_at"]
