import os

from django.core.management.base import BaseCommand

from accounts.models import Role, User, normalize_email


class Command(BaseCommand):
    help = (
        "Make DJANGO_SUPERUSER_EMAIL a site administrator (created if needed). "
        "No password: they log in with a code sent by email, like everyone."
    )

    def handle(self, *args, **options):
        email = normalize_email(os.environ.get("DJANGO_SUPERUSER_EMAIL", ""))
        if not email:
            return
        user, created = User.objects.get_or_create(email=email)
        if created:
            user.set_unusable_password()
        if created or not (user.is_superuser and user.is_staff and user.is_approved):
            user.is_superuser = user.is_staff = user.is_approved = True
            user.role = Role.ADMIN
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Site administrator: {email}"))
