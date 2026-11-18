import hashlib

from django.conf import settings
from django.utils import timezone
from django.contrib.gis.db import models

from accounts.models import Organization, VoterList


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


class AbsentDetail(models.TextChoices):
    """What was done when nobody answered (only for `VisitResult.ADDRESS_TO_RETRY`)."""

    LEAFLET = "leaflet", "Tract boîté"
    MAILBOX_INACCESSIBLE = "mailbox_inaccessible", "Boîte aux lettres inaccessible"


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


def address_key(name: str, first_names: str, address: str, zip_code: str, city: str) -> str:
    """Identity of an address across imports when the file gives no id.

    The name is semi-anonymized first: lists used to be stored that way ("Mar***"), so full names imported now
    still match those rows (and `semi_anonymize_name` is idempotent).
    """
    parts = [" ".join(str(p).lower().split()) for p in (semi_anonymize_name(name), first_names, address, zip_code, city)]
    return "k:" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:40]


class ActiveAddressManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(disabled_at__isnull=True)


class Address(models.Model):
    """A voter to visit, from a voter list (LEC) shared by the organizations depending on it.
    Addresses that disappeared from the latest import are disabled (`disabled_at`): kept for history and
    statistics, but hidden everywhere (`Address.objects` excludes them)."""

    voter_list = models.ForeignKey(VoterList, on_delete=models.CASCADE, related_name="addresses", verbose_name="LEC")
    name = models.CharField("nom d'usage", max_length=255)
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
    source_key = models.CharField(
        "clé d'import", max_length=255, blank=True, default="", help_text="Identifie l'adresse d'un import à l'autre."
    )
    disabled_at = models.DateTimeField(
        "désactivée le", null=True, blank=True, help_text="Absente du dernier import : plus visible par personne."
    )
    birth_year = models.PositiveSmallIntegerField("année de naissance", null=True, blank=True)
    # Address exactly as written in the imported list: tells whether a person moved since the last import
    # (the `address` field holds the geocoder's normalized spelling).
    source_address = models.CharField("adresse d'origine", max_length=512, blank=True, default="")

    objects = ActiveAddressManager()
    all_objects = models.Manager()

    class Meta:
        verbose_name = "adresse"
        base_manager_name = "all_objects"  # tour stops / visits keep pointing at disabled addresses
        indexes = [
            models.Index(fields=["voter_list", "status"], name="canvassing_address_list_status"),
            models.Index(fields=["voter_list", "source_key"], name="canvassing_address_list_key"),
        ]

    def save(self, *args, **kwargs):
        if not self.source_key:
            self.source_key = self.compute_key()
        super().save(*args, **kwargs)

    def compute_key(self) -> str:
        return address_key(self.name, self.first_names, self.address, self.zip_code, self.city)

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
    def first_name(self) -> str:
        return self.first_names.split(" ")[0] if self.first_names else ""


class District(models.Model):
    """A polling station district (Wahlbezirk), imported from the official electoral map: not editable.

    Carries the election result and census figures of the district, and a score (0–100) telling how likely
    canvassing there reaches our voters (see `services/scoring.py`).
    """

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="districts")
    code = models.CharField("numéro", max_length=32)
    name = models.CharField("nom", max_length=255)
    geometry = models.MultiPolygonField(srid=4326)
    # Lighter outline for the map, and a point inside the polygon to anchor its label.
    geometry_simple = models.MultiPolygonField(srid=4326, null=True, blank=True)
    label_point = models.PointField(srid=4326, null=True, blank=True)
    area_km2 = models.FloatField(default=0)

    # Election result (postal votes included when the source counts them separately).
    election = models.CharField("élection", max_length=128, blank=True, default="")
    eligible = models.FloatField("inscrit·es", null=True, blank=True)
    voters = models.FloatField("votant·es", null=True, blank=True)
    valid = models.FloatField("exprimés", null=True, blank=True)
    # Votes of the organization's reference party (sum of `Organization.reference_party_columns` in `parties`).
    reference_votes = models.FloatField("voix du parti de référence", null=True, blank=True)
    parties = models.JSONField("voix par parti", default=dict, blank=True)

    # Census 2022 (100 m grid cells whose centre lies in the district).
    population = models.IntegerField(null=True, blank=True)
    share_18_29 = models.FloatField(null=True, blank=True)
    share_65_plus = models.FloatField(null=True, blank=True)
    share_foreign = models.FloatField(null=True, blank=True)
    rent_m2 = models.FloatField("loyer net moyen (€/m²)", null=True, blank=True)
    # Social indicator of the organization (`Organization.social_label`): e.g. share of the residents living on
    # minimum social benefits (from `SocialArea`, weighted by census population), poverty rate, median income.
    social_value = models.FloatField("indicateur social", null=True, blank=True)

    score = models.FloatField(default=0, db_index=True)
    score_parts = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "bureau de vote"
        verbose_name_plural = "bureaux de vote"
        ordering = ["-score", "code"]
        constraints = [models.UniqueConstraint(fields=["organization", "code"], name="district_unique_code")]

    def __str__(self) -> str:
        return self.name


class DistrictImport(models.Model):
    """One import of the electoral map of an organization. Runs in a background thread (it takes a while)."""

    class ImportStatus(models.TextChoices):
        PENDING = "pending", "Fichiers reçus"
        RUNNING = "running", "En cours"
        DONE = "done", "Terminé"
        FAILED = "failed", "Échec"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="district_imports")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    source = models.CharField(max_length=32)  # a city pack key (`services/packs.py`) or "ai"
    status = models.CharField(max_length=16, choices=ImportStatus.choices, default=ImportStatus.PENDING)
    message = models.TextField(blank=True, default="")
    report = models.JSONField(default=dict, blank=True)
    # AI import: what the responsable asked for (election, source…), the agent session, and its steps.
    hint = models.TextField(blank=True, default="")
    ai_session_id = models.CharField(max_length=64, blank=True, default="")
    progress_log = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class CensusCell(models.Model):
    """A populated 100 m cell of the 2022 German census grid (shared by every organization)."""

    grid_id = models.CharField(max_length=40, unique=True)
    point = models.PointField(srid=4326)  # cell centre
    population = models.IntegerField()
    # Age counts are blank in small cells (statistical secrecy): `age_known` is the population they cover.
    age_known = models.IntegerField(default=0)
    age_18_29 = models.IntegerField(default=0)
    age_65_plus = models.IntegerField(default=0)
    share_foreign = models.FloatField(null=True)
    rent_m2 = models.FloatField(null=True)
    dwellings = models.IntegerField(null=True)


class SocialArea(models.Model):
    """A neighbourhood with a known social indicator.

    Shared by every organization (`organization` empty) - Berlin: the 542 "Planungsräume" of the Monitoring
    Soziale Stadtentwicklung (`manage.py load_social_index`), share of low-income residents - or found for one
    organization by the AI import (its own indicator, see `Organization.social_label`).
    Polling districts do not follow these borders: each district takes the population-weighted mean of the
    areas its census cells fall in.
    """

    organization = models.ForeignKey(
        Organization, null=True, blank=True, on_delete=models.CASCADE, related_name="social_areas"
    )
    source = models.CharField(max_length=32)
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    geometry = models.MultiPolygonField(srid=4326)
    population = models.IntegerField(null=True)
    low_income = models.FloatField(null=True)  # the indicator's value; None: not published (too few residents)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source", "code"], name="social_area_unique_code")]


class Tour(models.Model):
    class Kind(models.TextChoices):
        FREE = "free", "Tournée libre"
        PREDEFINED = "predefined", "Tournée préparée"

    class TourStatus(models.TextChoices):
        DRAFT = "draft", "Brouillon"
        ACTIVE = "active", "En cours"
        COMPLETED = "completed", "Terminée"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tours")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="tours")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=TourStatus.choices, default=TourStatus.DRAFT, db_index=True)
    area = models.ForeignKey(District, null=True, blank=True, on_delete=models.SET_NULL, related_name="tours")
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
    absent_detail = models.CharField(max_length=32, choices=AbsentDetail.choices, blank=True, default="")
    visited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["position"]


class Election(models.Model):
    """An election campaign (consular, presidential, legislative…). One is current for the whole site: new
    visits belong to it, and choosing another one starts the canvassing over (see `services/elections.py`)."""

    name = models.CharField("nom", max_length=128, unique=True)
    is_current = models.BooleanField("en cours", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField("en cours depuis", null=True, blank=True)

    class Meta:
        verbose_name = "élection"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["is_current"], condition=models.Q(is_current=True), name="one_current_election")
        ]

    def __str__(self) -> str:
        return self.name

    @classmethod
    def current(cls) -> "Election | None":
        return cls.objects.filter(is_current=True).first()


class Visit(models.Model):
    """Log of every feedback given on an address (given during a tour). Used for statistics."""

    address = models.ForeignKey(Address, on_delete=models.CASCADE, related_name="visits")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="visits")
    tour = models.ForeignKey(Tour, null=True, blank=True, on_delete=models.SET_NULL, related_name="visits")
    stop = models.OneToOneField(TourStop, null=True, blank=True, on_delete=models.SET_NULL, related_name="visit")
    result = models.CharField(max_length=32, choices=VisitResult.choices)
    absent_detail = models.CharField(max_length=32, choices=AbsentDetail.choices, blank=True, default="")
    election = models.ForeignKey(Election, null=True, blank=True, on_delete=models.SET_NULL, related_name="visits")
    # Visits imported from the Telegram bot: who made it there. Given to the member who links that Telegram account.
    telegram_user_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    # Not auto_now_add: visits imported from the Telegram bot keep their date.
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "visite"
        ordering = ["-created_at"]


class GeocodeCache(models.Model):
    """Result of geocoding one street address (shared by all imports): an address is only looked up once."""

    query = models.CharField(max_length=512, unique=True)
    found = models.BooleanField(default=False)
    street = models.CharField(max_length=255, blank=True, default="")
    zip_code = models.CharField(max_length=16, blank=True, default="")
    city = models.CharField(max_length=128, blank=True, default="")
    lat = models.FloatField(null=True)
    lon = models.FloatField(null=True)
    # When the address was sent to Google (only addresses OpenStreetMap could not locate): never sent twice.
    google_tried_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AddressImport(models.Model):
    """Import of a voter list (LEC), run in the background (geocoding takes a while)."""

    class ImportStatus(models.TextChoices):
        RUNNING = "running", "En cours"
        DONE = "done", "Terminé"
        FAILED = "failed", "Échec"

    voter_list = models.ForeignKey(VoterList, on_delete=models.CASCADE, related_name="imports")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    filename = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=16, choices=ImportStatus.choices, default=ImportStatus.RUNNING)
    message = models.TextField(blank=True, default="")
    report = models.JSONField(default=dict, blank=True)
    geocode_total = models.IntegerField(default=0)
    geocode_done = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class AiAgentConfig(models.Model):
    """The Claude Managed Agents agent + environment of the AI district import (`manage.py setup_ai_agent`).

    Created once, then updated in place; every import starts a session on them.
    """

    key = models.CharField(max_length=32, unique=True, default="districts")
    agent_id = models.CharField(max_length=64)
    agent_version = models.IntegerField(default=1)
    environment_id = models.CharField(max_length=64)
    updated_at = models.DateTimeField(auto_now=True)
