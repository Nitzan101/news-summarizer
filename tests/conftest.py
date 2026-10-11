import os

# Tests run under fixed settings, whatever the developer's shell or .env says:
# no scheduler, the mock summarizer (never a real AI API), default values.
# Set before the app is imported; a variable already set is not overridden by .env.
os.environ.update(
    {
        "SCHEDULER_ENABLED": "false",
        "SUMMARIZER": "mock",
        "GEMINI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "FETCH_QUERY": "technology",
        "FETCH_LIMIT": "20",
        "FETCH_INTERVAL_HOURS": "6",
        "SUMMARY_CACHE_TTL_SECONDS": "86400",
    }
)

import psycopg
import pytest
from sqlalchemy import text

from app.db import init_db, make_engine

TEST_DB_NAME = "news_test"
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", f"postgresql+psycopg://news:news@127.0.0.1:5433/{TEST_DB_NAME}"
)
ADMIN_URL = "postgresql://news:news@127.0.0.1:5433/postgres"
# The app uses Redis database 0; tests use database 1.
TEST_REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://127.0.0.1:6379/1")


def _create_test_database() -> None:
    # CREATE DATABASE cannot run inside a transaction, hence autocommit.
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_NAME,)
        ).fetchone()
        if not exists:
            conn.execute(f"CREATE DATABASE {TEST_DB_NAME}")


@pytest.fixture(scope="session")
def engine():
    """One engine for the whole test run, on a separate test database."""
    _create_test_database()
    engine = make_engine(TEST_DATABASE_URL)  # built exactly as the app builds its own
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS articles"))
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(request):
    """Empty the tables after every test that used the database."""
    yield
    if "engine" in request.fixturenames:
        engine = request.getfixturevalue("engine")
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE articles RESTART IDENTITY"))


@pytest.fixture
def cache():
    """A client on a separate Redis database (1), emptied around each test."""
    import redis

    client = redis.Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    client.flushdb()
    yield client
    client.flushdb()
    client.close()


@pytest.fixture
def api(engine, cache):
    """A test client whose requests use the test database and test cache."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.cache import get_redis
    from app.db import get_session
    from app.main import app

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_redis] = lambda: cache
    yield TestClient(app)
    app.dependency_overrides.clear()
