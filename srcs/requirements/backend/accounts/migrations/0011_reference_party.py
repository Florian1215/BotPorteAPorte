from django.db import migrations, models


def berlin_defaults(apps, schema_editor):
    # Existing organizations were imported with Die Linke as the reference party; the "linke" weight is now
    # "party" and "low_income" is now "social".
    Organization = apps.get_model("accounts", "Organization")
    for organization in Organization.objects.all():
        weights = dict(organization.score_weights or {})
        for old, new in (("linke", "party"), ("low_income", "social")):
            if old in weights:
                weights[new] = weights.pop(old)
        organization.score_weights = weights
        organization.reference_party_columns = ["Die Linke"]
        organization.save(update_fields=["score_weights", "reference_party_columns"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0010_voter_lists")]
    operations = [
        migrations.AddField(
            model_name="organization", name="reference_party",
            field=models.CharField(blank=True, default="Die Linke", max_length=128, verbose_name="parti de référence"),
        ),
        migrations.AddField(
            model_name="organization", name="reference_party_columns",
            field=models.JSONField(blank=True, default=list, verbose_name="colonnes du parti de référence"),
        ),
        migrations.AddField(
            model_name="organization", name="social_label",
            field=models.CharField(blank=True, default="Bas revenus", max_length=128, verbose_name="indicateur social"),
        ),
        migrations.AddField(
            model_name="organization", name="social_higher_is_poorer",
            field=models.BooleanField(default=True, verbose_name="plus haut = plus pauvre"),
        ),
        migrations.RunPython(berlin_defaults, migrations.RunPython.noop),
    ]
