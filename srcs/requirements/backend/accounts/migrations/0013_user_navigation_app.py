from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0012_age_criterion"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="navigation_app",
            field=models.CharField(
                choices=[("google", "Google Maps"), ("apple", "Apple Plans")],
                default="google",
                max_length=16,
                verbose_name="application de navigation",
            ),
        ),
    ]
