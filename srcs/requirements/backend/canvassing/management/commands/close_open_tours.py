"""Close every tour still open (run each morning by `run_scheduler`)."""
from django.core.management.base import BaseCommand

from canvassing.services.tours import close_open_tours


class Command(BaseCommand):
    help = "Close all open tours: finish the ones with knocked doors, discard the others, drop previews."

    def handle(self, *args, **opts):
        counts = close_open_tours()
        self.stdout.write(
            f"{counts['finished']} tournée(s) terminée(s), {counts['discarded']} abandonnée(s), "
            f"{counts['drafts_deleted']} brouillon(s) supprimé(s)."
        )
