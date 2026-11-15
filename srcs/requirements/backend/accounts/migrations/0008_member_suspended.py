from django.db import migrations, models
from django.utils import timezone


def mark_suspended(apps, schema_editor):
    """Accounts suspended before this field existed were simply "not approved": those that already went
    canvassing (a tour) had been approved once, so they are suspended members, not sign-ups to validate."""
    User = apps.get_model("accounts", "User")
    Tour = apps.get_model("canvassing", "Tour")
    canvassed = Tour.objects.values("user_id")
    User.objects.filter(is_approved=False, is_active=True, pk__in=canvassed).update(suspended_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0007_districts"),
        ("canvassing", "0010_retry_not_geocoded"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="suspended_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="suspendu·e le"),
        ),
        migrations.RunPython(mark_suspended, migrations.RunPython.noop),
    ]
