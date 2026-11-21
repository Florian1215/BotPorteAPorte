from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0013_user_navigation_app"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="route_display",
            field=models.CharField(
                choices=[("street", "Suivre les rues"), ("straight", "Lignes droites")],
                default="street",
                max_length=16,
                verbose_name="tracé des tournées",
            ),
        ),
    ]
