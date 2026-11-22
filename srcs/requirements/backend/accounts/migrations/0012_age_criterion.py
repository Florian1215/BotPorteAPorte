"""The "18–29 ans" criterion of the score becomes "âge" (LFI vote expected from the age of the French voters):
rename its weight, then recompute the scores."""
from django.db import migrations


def forwards(apps, schema_editor):
    Organization = apps.get_model("accounts", "Organization")
    for organization in Organization.objects.all():
        weights = dict(organization.score_weights or {})
        if "young" in weights:
            weights["age"] = weights.pop("young")
            organization.score_weights = weights
            organization.save(update_fields=["score_weights"])
    # Scores with the new criterion (the current code, once: districts are re-scored at every import anyway).
    # Only when there are districts: the current model may have columns a fresh database does not have yet.
    ids = list(Organization.objects.filter(districts__isnull=False).distinct().values_list("id", flat=True))
    if not ids:
        return
    from accounts.models import Organization as CurrentOrganization
    from canvassing.services import scoring

    for organization in CurrentOrganization.objects.filter(id__in=ids):
        scoring.rescore_organization(organization)


def backwards(apps, schema_editor):
    Organization = apps.get_model("accounts", "Organization")
    for organization in Organization.objects.all():
        weights = dict(organization.score_weights or {})
        if "age" in weights:
            weights["young"] = weights.pop("age")
            organization.score_weights = weights
            organization.save(update_fields=["score_weights"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0011_reference_party"),
        ("canvassing", "0019_visit_not_interested"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
