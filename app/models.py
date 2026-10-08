from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Article(Base):
    __tablename__ = "articles"

    # Our own id: primary key, used in the API's URLs.
    id: Mapped[int] = mapped_column(primary_key=True)
    # The story's id on Hacker News; unique so a re-fetch cannot duplicate it.
    hn_id: Mapped[int] = mapped_column(unique=True)
    title: Mapped[str]
    url: Mapped[str | None]
    author: Mapped[str]
    points: Mapped[int]
    num_comments: Mapped[int]
    story_text: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
