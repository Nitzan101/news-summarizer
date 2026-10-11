"""The app must survive Postgres closing its pooled connections.

Found in a real run: after Postgres restarted under the running service, the
next request failed with "server closed the connection unexpectedly".
"""

import psycopg
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import make_engine
from tests.conftest import ADMIN_URL, TEST_DATABASE_URL, TEST_DB_NAME


def close_all_connections_to_test_database() -> int:
    """Do to the pool what a Postgres restart does: kill its open connections."""
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        rows = admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (TEST_DB_NAME,),
        ).fetchall()
    return len(rows)


def test_request_after_postgres_closed_the_pooled_connection_still_works(engine):
    app_engine = make_engine(TEST_DATABASE_URL)
    try:
        with Session(app_engine) as session:
            session.execute(text("SELECT 1"))  # the connection now sits in the pool

        assert close_all_connections_to_test_database() >= 1

        with Session(app_engine) as session:  # reuses the pooled, now dead, connection
            assert session.execute(text("SELECT 1")).scalar() == 1
    finally:
        app_engine.dispose()
