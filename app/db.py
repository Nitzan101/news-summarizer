from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Parent class of every model; collects their table definitions."""


def make_engine(url: str):
    """An engine whose pooled connections are checked before each use.

    The pool keeps connections open between requests. Postgres can close one
    in the meantime (a restart, a network drop, a long idle period), and the
    next request would then fail on a dead connection. pool_pre_ping tests the
    connection first and silently replaces it if it is dead.
    """
    return create_engine(url, pool_pre_ping=True)


# One engine for the whole app. It does not connect until first used.
engine = make_engine(settings.database_url)

# Factory for sessions bound to that engine: SessionLocal() opens a new one.
SessionLocal = sessionmaker(bind=engine)


def init_db(bind=engine) -> None:
    """Create any tables that do not exist yet (does not alter existing ones)."""
    from app import models  # noqa: F401  importing registers the models on Base

    Base.metadata.create_all(bind)


def get_session():
    """FastAPI dependency: one session per request, closed when it ends."""
    with SessionLocal() as session:
        yield session
