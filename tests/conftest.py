import os

import psycopg
import pytest
from sqlalchemy import create_engine, text

from app.db import init_db

TEST_DB_NAME = "news_test"
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", f"postgresql+psycopg://news:news@localhost:5433/{TEST_DB_NAME}"
)
ADMIN_URL = "postgresql://news:news@localhost:5433/postgres"


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
    engine = create_engine(TEST_DATABASE_URL)
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
