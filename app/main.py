import logging
from contextlib import asynccontextmanager

import httpx
import redis
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cache import cache_summary, get_cached_summary, get_redis
from app.config import settings
from app.content import get_page_client, text_to_summarize
from app.db import get_session, init_db
from app.fetcher import run_fetch
from app.hn_client import get_hn_client
from app.models import Article
from app.scheduler import build_scheduler
from app.schemas import ArticleOut, ArticlePage, SummaryOut
from app.summarizer import Summarizer, SummarizerError, get_summarizer


# Show our own INFO messages (e.g. the scheduler's) next to uvicorn's.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Before the yield: runs once when the server starts.
    init_db()
    scheduler = build_scheduler() if settings.scheduler_enabled else None
    if scheduler:
        scheduler.start()
    yield
    # After the yield: runs once when the server shuts down.
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="News Summarizer", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/fetch")
def fetch(
    session: Session = Depends(get_session),
    client: httpx.Client = Depends(get_hn_client),
) -> dict[str, int]:
    """Fetch the newest stories from Hacker News now and store them."""
    try:
        fetched = run_fetch(session, client)
    except httpx.HTTPError:
        # The failure is upstream, not ours and not the caller's: 502.
        raise HTTPException(status_code=502, detail="Hacker News is unavailable")
    return {"fetched": fetched}


@app.get("/articles", response_model=ArticlePage)
def list_articles(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    session: Session = Depends(get_session),
):
    """One page of articles, newest first."""
    total = session.scalar(select(func.count()).select_from(Article))
    items = session.scalars(
        select(Article)
        # id breaks ties, so the order is stable from page to page.
        .order_by(Article.created_at.desc(), Article.id.desc())
        .limit(size)
        .offset((page - 1) * size)
    ).all()
    return {"items": items, "total": total, "page": page, "size": size}


@app.get("/articles/{article_id}", response_model=ArticleOut)
def get_article(article_id: int, session: Session = Depends(get_session)):
    article = session.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@app.get("/articles/{article_id}/summary", response_model=SummaryOut)
def get_summary(
    article_id: int,
    session: Session = Depends(get_session),
    page_client: httpx.Client = Depends(get_page_client),
    summarizer: Summarizer = Depends(get_summarizer),
    cache: redis.Redis = Depends(get_redis),
):
    article = session.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    # Cache-aside: answer from the cache when we can...
    cached = get_cached_summary(cache, article.id)
    if cached is not None:
        return {**cached, "cached": True}

    # ...otherwise do the slow work and remember the result.
    text, source = text_to_summarize(article, page_client)
    try:
        summary = summarizer.summarize(article.title, text)
    except SummarizerError:
        raise HTTPException(status_code=502, detail="Summarizer is unavailable")
    result = {"article_id": article.id, "summary": summary, "source": source}
    cache_summary(cache, article.id, result)
    return {**result, "cached": False}
