from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session, init_db
from app.fetcher import run_fetch
from app.hn_client import get_hn_client


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
