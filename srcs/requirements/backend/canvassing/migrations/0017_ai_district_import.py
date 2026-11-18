import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0011_reference_party"),
        ("canvassing", "0016_geocodecache_google_tried_at"),
    ]
    operations = [
        migrations.RenameField(model_name="district", old_name="linke", new_name="reference_votes"),
        migrations.AlterField(
            model_name="district", name="reference_votes",
            field=models.FloatField(blank=True, null=True, verbose_name="voix du parti de référence"),
        ),
        migrations.RenameField(model_name="district", old_name="low_income", new_name="social_value"),
        migrations.AlterField(
            model_name="district", name="social_value",
            field=models.FloatField(blank=True, null=True, verbose_name="indicateur social"),
        ),
        migrations.AddField(model_name="districtimport", name="hint", field=models.TextField(blank=True, default="")),
        migrations.AddField(
            model_name="districtimport", name="ai_session_id", field=models.CharField(blank=True, default="", max_length=64)
        ),
        migrations.AddField(model_name="districtimport", name="progress_log", field=models.JSONField(blank=True, default=list)),
        migrations.AddField(
            model_name="socialarea", name="organization",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="social_areas",
                to="accounts.organization",
            ),
        ),
        migrations.CreateModel(
            name="AiAgentConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(default="districts", max_length=32, unique=True)),
                ("agent_id", models.CharField(max_length=64)),
                ("agent_version", models.IntegerField(default=1)),
                ("environment_id", models.CharField(max_length=64)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
