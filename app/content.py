"""Finds the text to summarize for an article."""

from collections.abc import Iterator

import httpx
from bs4 import BeautifulSoup

from app.models import Article

TIMEOUT_SECONDS = 10.0
# Summarizing is paid per amount of text, so cap what we send.
MAX_CHARS = 8000
# A page with less text than this is an error page or a login wall, not an article.
MIN_PAGE_CHARS = 200
# Parts of a page that are never the article itself.
NOISE_TAGS = ["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]


def get_page_client() -> Iterator[httpx.Client]:
    """FastAPI dependency: an HTTP client for fetching linked pages."""
    with httpx.Client(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": "news-summarizer/1.0"},
    ) as client:
        yield client


def html_to_text(html: str) -> str:
    """Strip tags and page chrome, leaving plain text with single spaces."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(NOISE_TAGS):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())


def fetch_page_text(client: httpx.Client, url: str) -> str | None:
    """The text of the page at url, or None if it cannot be used."""
    if not url.startswith(("http://", "https://")):
        return None
    try:
        response = client.get(url)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    if "html" not in response.headers.get("content-type", ""):
        return None  # a PDF, an image, a video...
    text = html_to_text(response.text)
    return text if len(text) >= MIN_PAGE_CHARS else None


def text_to_summarize(article: Article, client: httpx.Client) -> tuple[str, str]:
    """Return (text, source): the linked page, else the story text, else the title."""
    if article.url:
        page_text = fetch_page_text(client, article.url)
        if page_text:
            return page_text[:MAX_CHARS], "page"
    if article.story_text:
        return html_to_text(article.story_text)[:MAX_CHARS], "story_text"
    return article.title, "title"
