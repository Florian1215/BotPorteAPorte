from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from canvassing.services import ai_import


class Command(BaseCommand):
    help = "Create (or update) the Claude Managed Agents agent and environment of the AI district import."

    def handle(self, *args, **options):
        if not settings.ANTHROPIC_API_KEY:
            raise CommandError("ANTHROPIC_API_KEY is not set (srcs/.env).")
        config = ai_import.ensure_agent()
        self.stdout.write(self.style.SUCCESS(
            f"Agent {config.agent_id} (version {config.agent_version}), environment {config.environment_id}."
        ))
