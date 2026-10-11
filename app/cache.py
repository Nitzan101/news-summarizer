"""Summary cache in Redis, used cache-aside by the summary endpoint.

The cache only makes things faster. If Redis is unreachable the service
keeps working without it, so every Redis error here is swallowed.
"""

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


def get_redis() -> redis.Redis:
    """FastAPI dependency: the Redis client."""
    return redis_client


def summary_key(article_id: int) -> str:
    return f"summary:{article_id}"


def get_cached_summary(client: redis.Redis, article_id: int) -> dict | None:
    """The cached summary for this article, or None if there is none."""
    try:
        raw = client.get(summary_key(article_id))
    except redis.RedisError:
        return None
    return json.loads(raw) if raw else None


def cache_summary(client: redis.Redis, article_id: int, summary: dict) -> None:
    """Store the summary; Redis deletes it by itself when the TTL runs out."""
    try:
        client.set(
            summary_key(article_id),
            json.dumps(summary),
            ex=settings.summary_cache_ttl_seconds,
        )
    except redis.RedisError:
        pass
