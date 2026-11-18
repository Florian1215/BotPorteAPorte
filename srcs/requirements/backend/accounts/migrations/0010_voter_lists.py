from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_telegram_link"),
    ]

    operations = [
        migrations.CreateModel(
            name="VoterList",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=128, verbose_name="nom")),
                (
                    "country_code",
                    models.CharField(
                        default="DE",
                        help_text="Code pays ISO 3166-1 alpha-2 des adresses, pour le géocodage.",
                        max_length=2,
                        verbose_name="pays",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "liste électorale consulaire (LEC)",
                "verbose_name_plural": "listes électorales consulaires (LEC)",
                "ordering": ["name"],
            },
        ),
        migrations.AddField(
            model_name="organization",
            name="voter_list",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="organizations",
                to="accounts.voterlist",
                verbose_name="LEC",
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="radius_km",
            field=models.PositiveIntegerField(
                default=30,
                help_text="Adresses de la LEC prises en compte autour de la ville de l'organisation.",
                verbose_name="rayon (km)",
            ),
        ),
        migrations.AlterField(
            model_name="organization",
            name="country_code",
            field=models.CharField(
                default="DE", help_text="Code pays ISO 3166-1 alpha-2 (déduit de la ville).", max_length=2, verbose_name="pays"
            ),
        ),
    ]
