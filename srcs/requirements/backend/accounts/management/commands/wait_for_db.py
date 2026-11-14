import time

from django.core.management.base import BaseCommand
from django.db import connections
from django.db.utils import OperationalError


class Command(BaseCommand):
    help = "Wait until the database accepts connections."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=60)

    def handle(self, *args, timeout, **options):
        deadline = time.monotonic() + timeout
        while True:
            try:
                connections["default"].ensure_connection()
                self.stdout.write("Database available.")
                return
            except OperationalError:
                if time.monotonic() > deadline:
                    raise
                self.stdout.write("Waiting for database...")
                time.sleep(1)
