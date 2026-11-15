from django.db import migrations, models
import django.db.models.deletion


def superusers_are_admins(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(is_superuser=True).update(role="admin")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RenameModel("Scope", "Organization"),
        migrations.AlterModelOptions(name="organization", options={"ordering": ["name"], "verbose_name": "organisation"}),
        migrations.AlterField(
            model_name="organization",
            name="name",
            field=models.CharField(max_length=128, verbose_name="nom"),
        ),
        migrations.AlterField(
            model_name="organization",
            name="country_code",
            field=models.CharField(
                default="DE",
                help_text="Code pays ISO 3166-1 alpha-2, utilisé pour le géocodage.",
                max_length=2,
                verbose_name="pays",
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="logo",
            field=models.BinaryField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="organization",
            name="logo_content_type",
            field=models.CharField(blank=True, default="", editable=False, max_length=32),
        ),
        migrations.AddField(
            model_name="organization",
            name="logo_updated_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.RenameField(model_name="user", old_name="scope", new_name="organization"),
        migrations.AlterField(
            model_name="user",
            name="organization",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="members",
                to="accounts.organization",
                verbose_name="organisation",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("militant", "Militant·e"),
                    ("experienced", "Militant·e aguerri·e"),
                    ("manager", "Responsable d'organisation"),
                    ("admin", "Administrateur·rice du site"),
                ],
                default="militant",
                max_length=16,
                verbose_name="rôle",
            ),
        ),
        migrations.RunPython(superusers_are_admins, migrations.RunPython.noop),
    ]
