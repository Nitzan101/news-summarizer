from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Parent class of every model; collects their table definitions."""


# One engine for the whole app. It does not connect until first used.
engine = create_engine(settings.database_url)

# Factory for sessions bound to that engine: SessionLocal() opens a new one.
SessionLocal = sessionmaker(bind=engine)


def init_db(bind=engine) -> None:
    """Create any tables that do not exist yet (does not alter existing ones)."""
    from app import models  # noqa: F401  importing registers the models on Base

    Base.metadata.create_all(bind)
