from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session, init_db
from app.fetcher import run_fetch
from app.hn_client import get_hn_client
from app.models import Article
from app.schemas import ArticleOut, ArticlePage


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once when the server starts: make sure the tables exist.
    init_db()
    yield


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
