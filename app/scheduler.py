"""Runs the fetch on a schedule, in a background thread of the app."""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.db import SessionLocal
from app.fetcher import run_fetch
from app.hn_client import new_hn_client

logger = logging.getLogger(__name__)


def scheduled_fetch(session_factory=SessionLocal, client_factory=new_hn_client) -> None:
    """One scheduled run: fetch and store, never raise.

    There is no HTTP request here, so no Depends: the job opens and closes
    its own session and HTTP client. A failure is logged and the next run
    simply tries again.
    """
    try:
        with session_factory() as session, client_factory() as client:
            fetched = run_fetch(session, client)
    except Exception:
        logger.exception("Scheduled fetch failed")
        return
    logger.info("Scheduled fetch stored %d articles", fetched)


def build_scheduler() -> BackgroundScheduler:
    """A scheduler with the fetch job: once right away, then every N hours."""
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        scheduled_fetch,
        "interval",
        hours=settings.fetch_interval_hours,
        # Without this the first run would be a full interval after startup,
        # leaving a fresh install with an empty database for hours.
        next_run_time=datetime.now(timezone.utc),
        id="fetch",
        # If a run is still going when the next is due, skip instead of overlapping.
        max_instances=1,
        coalesce=True,
        # Run a job however late it starts. The default drops a run that is more
        # than 1 s overdue, which on a slow startup would skip the first fetch.
        misfire_grace_time=None,
    )
    return scheduler
