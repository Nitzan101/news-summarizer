import logging
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
import redis
from fastapi import Depends, FastAPI, HTTPException, Path, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.cache import cache_summary, get_cached_summary, get_redis, summary_fingerprint
from app.config import settings
from app.content import get_page_client, text_to_summarize
from app.db import get_session, init_db
from app.fetcher import run_fetch
from app.hn_client import HackerNewsError, get_hn_client
from app.models import Article
from app.scheduler import build_scheduler
from app.schemas import ArticleOut, ArticlePage, SummaryOut
from app.summarizer import Summarizer, SummarizerError, build_summarizer, get_summarizer


# Show our own INFO messages (e.g. the scheduler's) next to uvicorn's.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Before the yield: runs once when the server starts.
    # Fail at startup, not on the first request, if SUMMARIZER is misconfigured.
    build_summarizer()
    init_db()
    scheduler = build_scheduler() if settings.scheduler_enabled else None
    if scheduler:
        scheduler.start()
    yield
    # After the yield: runs once when the server shuts down.
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="News Summarizer", lifespan=lifespan)

# The id column is a 32-bit integer: a larger number can never match a row,
# and passing it to Postgres would raise instead of returning 404.
ArticleId = Annotated[int, Path(ge=1, le=2_147_483_647)]
# Far beyond any real page, and small enough that the offset fits in Postgres.
MAX_PAGE = 1_000_000

NOT_FOUND = {404: {"description": "No article with this id"}}
BAD_GATEWAY = {"description": "An external service the request depends on failed"}


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is running. It checks nothing else."""
    return {"status": "ok"}


@app.get("/ready", responses={503: {"description": "The database does not answer"}})
def ready(session: Session = Depends(get_session)) -> dict[str, str]:
    """Readiness: the service can do its work, which needs the database.

    Redis is not checked: the cache is optional and the service works without it.
    """
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        # Log the cause here; the caller only needs to know it is not ready.
        logger.exception("Readiness check failed")
        raise HTTPException(status_code=503, detail="Not ready")
    return {"status": "ok"}


@app.post("/fetch", responses={502: BAD_GATEWAY})
def fetch(
    session: Session = Depends(get_session),
    client: httpx.Client = Depends(get_hn_client),
) -> dict[str, int]:
    """Fetch the newest stories from Hacker News now and store them."""
    try:
        fetched = run_fetch(session, client)
    except HackerNewsError:
        # The failure is upstream, not ours and not the caller's: 502.
        raise HTTPException(status_code=502, detail="Hacker News is unavailable")
    return {"fetched": fetched}


@app.get("/articles", response_model=ArticlePage)
def list_articles(
    page: int = Query(1, ge=1, le=MAX_PAGE),
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


@app.get("/articles/{article_id}", response_model=ArticleOut, responses=NOT_FOUND)
def get_article(article_id: ArticleId, session: Session = Depends(get_session)):
    article = session.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@app.get(
    "/articles/{article_id}/summary",
    response_model=SummaryOut,
    responses={**NOT_FOUND, 502: BAD_GATEWAY},
)
def get_summary(
    article_id: ArticleId,
    session: Session = Depends(get_session),
    page_client: httpx.Client = Depends(get_page_client),
    summarizer: Summarizer = Depends(get_summarizer),
    cache: redis.Redis = Depends(get_redis),
):
    article = session.get(Article, article_id)
    # The database is not needed from here on, and the slow work below (a page
    # download, an AI call) can take up to 40 seconds. Give the connection back to
    # the pool now instead of holding it until the request ends. The article keeps
    # the values it already loaded.
    session.close()
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    # The key changes when the article, the summarizer or the model changes.
    fingerprint = summary_fingerprint(article.title, article.url, article.story_text)

    # Cache-aside: answer from the cache when we can...
    cached = get_cached_summary(cache, article.id, fingerprint)
    if cached is not None:
        return {**cached, "cached": True}

    # ...otherwise do the slow work and remember the result.
    text, source = text_to_summarize(article, page_client)
    try:
        summary = summarizer.summarize(article.title, text)
    except SummarizerError:
        raise HTTPException(status_code=502, detail="Summarizer is unavailable")
    result = {"article_id": article.id, "summary": summary, "source": source}
    cache_summary(cache, article.id, fingerprint, result)
    return {**result, "cached": False}
