"""The only module that knows how to talk to Hacker News."""

from collections.abc import Iterator

import httpx

# Algolia's HN search, newest first.
SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
TIMEOUT_SECONDS = 10.0


def new_hn_client() -> httpx.Client:
    """A client for Hacker News; the caller closes it (use `with`)."""
    return httpx.Client(timeout=TIMEOUT_SECONDS)


def get_hn_client() -> Iterator[httpx.Client]:
    """FastAPI dependency: an HTTP client, closed when the request ends."""
    with new_hn_client() as client:
        yield client


def fetch_stories(client: httpx.Client, query: str, limit: int) -> list[dict]:
    """Return the newest stories matching the query, as raw JSON objects."""
    response = client.get(
        SEARCH_URL,
        # tags=story: without it the search also returns comments,
        # which have different fields.
        params={"query": query, "tags": "story", "hitsPerPage": limit},
    )
    response.raise_for_status()
    return response.json()["hits"]
