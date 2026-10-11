"""The only module that knows how to talk to Hacker News."""

from collections.abc import Iterator

import httpx

class HackerNewsError(Exception):
    """Hacker News could not be reached or did not return a list of stories."""


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
    """Return the newest stories matching the query, as raw JSON objects.

    Raises HackerNewsError for every way the upstream can fail us: no answer,
    an error status, or a 200 whose body is not the JSON we expect.
    """
    try:
        response = client.get(
            SEARCH_URL,
            # tags=story: without it the search also returns comments,
            # which have different fields.
            params={"query": query, "tags": "story", "hitsPerPage": limit},
        )
        response.raise_for_status()
        hits = response.json()["hits"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        raise HackerNewsError(f"Hacker News request failed: {error!r}") from error
    if not isinstance(hits, list):
        raise HackerNewsError("Hacker News did not return a list of stories")
    return hits
