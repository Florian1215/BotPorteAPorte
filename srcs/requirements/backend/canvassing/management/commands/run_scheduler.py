"""Tiny in-process scheduler (the `scheduler` service of docker-compose): no cron/celery needed.

Every day at CANVASSING_TOURS_CLOSE_TIME (local TIME_ZONE, default 06:00), all open tours are closed.
"""
import logging
import time
from datetime import datetime, timedelta

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

logger = logging.getLogger(__name__)


def next_run(now: datetime, hour: int, minute: int) -> datetime:
    run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if run <= now:
        run += timedelta(days=1)  # wall-clock arithmetic with zoneinfo: stays at HH:MM across DST changes
    return run


class Command(BaseCommand):
    help = "Run the daily jobs (closing of open tours) forever."

    def handle(self, *args, **opts):
        hour, minute = (int(x) for x in settings.CANVASSING_TOURS_CLOSE_TIME.split(":"))
        while True:
            run = next_run(timezone.localtime(), hour, minute)
            logger.info("Next closing of open tours: %s", run.isoformat())
            while (delay := (run - timezone.localtime()).total_seconds()) > 0:
                time.sleep(min(delay, 300))  # short naps: robust to clock jumps / container suspend
            close_old_connections()
            try:
                call_command("close_open_tours")
            except Exception:
                logger.exception("Closing of open tours failed")
            finally:
                close_old_connections()
