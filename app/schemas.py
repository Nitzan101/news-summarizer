"""The JSON shapes the API returns (Pydantic models, not database tables)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ArticleOut(BaseModel):
    # Lets FastAPI build this from an Article object by reading its attributes.
    model_config = ConfigDict(from_attributes=True)

    id: int
    hn_id: int
    title: str
    url: str | None
    author: str
    points: int
    num_comments: int
    story_text: str | None
    created_at: datetime
    fetched_at: datetime


class ArticlePage(BaseModel):
    items: list[ArticleOut]
    total: int  # all articles in the database, not just this page
    page: int
    size: int


class SummaryOut(BaseModel):
    article_id: int
    summary: str
    source: str  # what was summarized: "page", "story_text" or "title"
    cached: bool  # True when this answer came from the cache
