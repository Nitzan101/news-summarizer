"""Summary cache in Redis, used cache-aside by the summary endpoint.

The cache only makes things faster. If Redis is unreachable the service
keeps working without it, so every Redis error here is swallowed.
"""

import hashlib
import json

import redis

from app.config import settings

# One client for the whole app (it keeps a connection pool, like the DB engine).
# It does not connect until first used. Short timeouts: a slow cache is worse
# than no cache.
redis_client = redis.Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


# Where a summary's text can come from (see app/content.py).
SUMMARY_SOURCES = {"page", "story_text", "title"}


def get_redis() -> redis.Redis:
    """FastAPI dependency: the Redis client."""
    return redis_client


def summary_fingerprint(title: str, url: str | None, story_text: str | None) -> str:
    """A short hash of everything a summary depends on: who writes it and what it reads.

    It is part of the cache key, so a changed article, a different summarizer or a
    different model finds no entry and gets a fresh summary. The old entry is never
    asked for again and disappears when its TTL runs out.
    """
    model = {"gemini": settings.gemini_model, "claude": settings.anthropic_model}
    provider = f"{settings.summarizer}:{model.get(settings.summarizer, '')}"
    raw = f"{provider}\0{title}\0{url or ''}\0{story_text or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def summary_key(article_id: int, fingerprint: str) -> str:
    return f"summary:{article_id}:{fingerprint}"


def get_cached_summary(client: redis.Redis, article_id: int, fingerprint: str) -> dict | None:
    """The cached summary for this article, or None if there is none."""
    try:
        raw = client.get(summary_key(article_id, fingerprint))
        cached = json.loads(raw) if raw else None
    except (redis.RedisError, ValueError):  # Redis is down, or the value is not JSON
        return None
    # Anything that is not a summary we wrote is treated as a miss and overwritten.
    if not isinstance(cached, dict):
        return None
    summary = cached.get("summary")
    if (
        cached.get("article_id") != article_id
        or not isinstance(summary, str)
        or not summary.strip()
        or cached.get("source") not in SUMMARY_SOURCES
    ):
        return None
    return cached


def cache_summary(client: redis.Redis, article_id: int, fingerprint: str, summary: dict) -> None:
    """Store the summary; Redis deletes it by itself when the TTL runs out."""
    try:
        client.set(
            summary_key(article_id, fingerprint),
            json.dumps(summary),
            ex=settings.summary_cache_ttl_seconds,
        )
    except redis.RedisError:
        pass
