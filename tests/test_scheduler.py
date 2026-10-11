import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Article
from app.scheduler import build_scheduler, scheduled_fetch
from tests.hn_fakes import LINK_STORY, TEXT_STORY, fake_hn_client


def count_articles(engine) -> int:
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(Article))


def test_scheduled_fetch_stores_articles(engine):
    scheduled_fetch(
        session_factory=lambda: Session(engine),
        client_factory=lambda: fake_hn_client([LINK_STORY, TEXT_STORY]),
    )

    assert count_articles(engine) == 2


def test_scheduled_fetch_logs_a_failure_instead_of_raising(engine, caplog):
    with caplog.at_level(logging.ERROR):
        scheduled_fetch(
            session_factory=lambda: Session(engine),
            client_factory=lambda: fake_hn_client([], status_code=503),
        )

    assert "Scheduled fetch failed" in caplog.text
    assert count_articles(engine) == 0


def test_scheduler_runs_the_fetch_now_and_then_every_six_hours():
    scheduler = build_scheduler()

    [job] = scheduler.get_jobs()

    assert job.func is scheduled_fetch
    assert job.trigger.interval == timedelta(hours=6)
    assert abs(job.next_run_time - datetime.now(timezone.utc)) < timedelta(seconds=5)
