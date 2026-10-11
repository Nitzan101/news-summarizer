import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://news:news@localhost:5433/news"
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    summarizer: str = os.getenv("SUMMARIZER", "mock")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
    # What the fetcher asks Hacker News for, and how many stories per fetch.
    fetch_query: str = os.getenv("FETCH_QUERY", "technology")
    fetch_limit: int = int(os.getenv("FETCH_LIMIT", "20"))
    # The scheduler: how often it fetches, and a switch to turn it off (tests).
    fetch_interval_hours: float = float(os.getenv("FETCH_INTERVAL_HOURS", "6"))
    scheduler_enabled: bool = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"
    # How long a cached summary lives in Redis (default: 24 hours).
    summary_cache_ttl_seconds: int = int(os.getenv("SUMMARY_CACHE_TTL_SECONDS", "86400"))


settings = Settings()
