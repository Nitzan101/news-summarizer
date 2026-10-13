"""Turns Hacker News stories into rows of the articles table."""

import logging
from datetime import datetime

import httpx
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.hn_client import fetch_stories
from app.models import Article

logger = logging.getLogger(__name__)


def _text(value: object, field: str, required: bool) -> str | None:
    """The value if it is a string (or, when optional, missing); else TypeError."""
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise TypeError(field)
    return value


def _count(value: object, field: str) -> int:
    """The value if it is a whole number (a missing one counts as 0); else TypeError."""
    value = value or 0
    if type(value) is not int:  # bool is a subclass of int, so isinstance would let it in
        raise TypeError(field)
    return value


def to_article_fields(hit: dict) -> dict:
    """Map one story from the HN response to Article columns.

    A value of the wrong type raises TypeError here, so upsert_articles skips that
    story. Left alone, it would make the database reject the single INSERT that
    holds every story, and the good ones would be lost with it.
    """
    return {
        "hn_id": int(hit["objectID"]),  # arrives as a string
        "title": _text(hit["title"], "title", required=True),
        "url": _text(hit.get("url"), "url", required=False),  # absent on text posts
        "author": _text(hit["author"], "author", required=True),
        "points": _count(hit.get("points"), "points"),
        "num_comments": _count(hit.get("num_comments"), "num_comments"),
        "story_text": _text(hit.get("story_text"), "story_text", required=False),
        "created_at": datetime.fromisoformat(hit["created_at"]),
    }


def upsert_articles(session: Session, hits: list[dict]) -> int:
    """Insert new stories and update ones we already have. Returns the count."""
    # Keyed by hn_id: one statement cannot upsert the same row twice.
    rows = {}
    for hit in hits:
        try:
            fields = to_article_fields(hit)
        except (KeyError, TypeError, ValueError):
            # One malformed story must not cost us the other nineteen.
            logger.warning("Skipping malformed story %r", hit.get("objectID"))
            continue
        if not fields["title"] or not fields["author"]:
            logger.warning("Skipping story %s with no title or author", fields["hn_id"])
            continue
        rows[fields["hn_id"]] = fields
    if not rows:
        return 0

    statement = insert(Article).values(list(rows.values()))
    statement = statement.on_conflict_do_update(
        index_elements=[Article.hn_id],
        set_={
            "title": statement.excluded.title,
            "url": statement.excluded.url,
            "points": statement.excluded.points,
            "num_comments": statement.excluded.num_comments,
            "story_text": statement.excluded.story_text,
            "fetched_at": func.now(),
        },
    )
    session.execute(statement)
    session.commit()
    return len(rows)


def run_fetch(session: Session, client: httpx.Client) -> int:
    """Fetch the newest stories for the configured query and store them."""
    hits = fetch_stories(client, settings.fetch_query, settings.fetch_limit)
    return upsert_articles(session, hits)
