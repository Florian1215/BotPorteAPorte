"""Before switching to email login: every account needs a unique, lowercase email.

Accounts without one get a placeholder `<username>@utilisateur.invalid` (reserved TLD, never delivered):
a manager or admin can replace it with the person's real address from the members screen or /admin/.
"""
from django.db import migrations


def fill_emails(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    seen = set()
    for user in User.objects.order_by("-is_superuser", "-last_login", "id"):
        email = (user.email or "").strip().lower()
        if not email or email in seen:
            email = f"{user.username.lower()}@utilisateur.invalid"
        seen.add(email)
        if email != user.email:
            user.email = email
            user.save(update_fields=["email"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_organizations_and_roles"),
    ]

    operations = [migrations.RunPython(fill_emails, migrations.RunPython.noop)]
