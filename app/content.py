"""Finds the text to summarize for an article."""

import ipaddress
import socket
from collections.abc import Iterator

import httpx
from bs4 import BeautifulSoup

from app.models import Article

TIMEOUT_SECONDS = 10.0
# Summarizing is paid per amount of text, so cap what we send.
MAX_CHARS = 8000
# A page with less text than this is an error page or a login wall, not an article.
MIN_PAGE_CHARS = 200
# A story link is chosen by strangers, so never read more than this from one page...
MAX_PAGE_BYTES = 1_000_000
# ...and never follow more redirects than this.
MAX_REDIRECTS = 3
# Parts of a page that are never the article itself.
NOISE_TAGS = ["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]


def get_page_client() -> Iterator[httpx.Client]:
    """FastAPI dependency: an HTTP client for fetching linked pages."""
    with httpx.Client(
        timeout=TIMEOUT_SECONDS,
        # Redirects are followed by hand in fetch_page_text, so each hop can be checked.
        follow_redirects=False,
        headers={"User-Agent": "news-summarizer/1.0"},
    ) as client:
        yield client


def html_to_text(html: str) -> str:
    """Strip tags and page chrome, leaving plain text with single spaces."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(NOISE_TAGS):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())


def is_public_http_url(url: str) -> bool:
    """True only for an http(s) URL whose host resolves to public internet addresses.

    Blocks loopback, private, link-local and Docker-network hosts (SSRF): a story
    link is chosen by strangers and must not make this server read its own network.
    """
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.host or parsed.userinfo:
        return False
    try:
        infos = socket.getaddrinfo(parsed.host, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError:  # the name does not resolve
        return False
    addresses = {info[4][0].split("%")[0] for info in infos}  # drop an IPv6 zone id
    try:
        # Every address must be public: a name with one private address is refused.
        return bool(addresses) and all(ipaddress.ip_address(a).is_global for a in addresses)
    except ValueError:
        return False


def fetch_page_text(client: httpx.Client, url: str) -> str | None:
    """The text of the page at url, or None if it cannot be used."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if not is_public_http_url(current):  # checked again on every redirect hop
            return None
        try:
            with client.stream("GET", current) as response:
                if response.is_redirect:
                    location = response.headers.get("location", "")
                    current = str(response.url.join(location))
                    continue
                response.raise_for_status()
                # Decide from the headers, before downloading anything.
                if "html" not in response.headers.get("content-type", ""):
                    return None  # a PDF, an image, a video...
                body = bytearray()
                for chunk in response.iter_bytes():  # also caps a gzip bomb
                    body.extend(chunk)
                    if len(body) > MAX_PAGE_BYTES:
                        return None
                html = body.decode(response.encoding or "utf-8", errors="replace")
        except (httpx.HTTPError, httpx.InvalidURL, ValueError, LookupError):
            # InvalidURL is not an HTTPError: the link itself is malformed.
            # LookupError: the page named a character set Python does not know.
            return None
        text = html_to_text(html)
        return text if len(text) >= MIN_PAGE_CHARS else None
    return None  # too many redirects


def text_to_summarize(article: Article, client: httpx.Client) -> tuple[str, str]:
    """Return (text, source): the linked page, else the story text, else the title."""
    if article.url:
        page_text = fetch_page_text(client, article.url)
        if page_text:
            return page_text[:MAX_CHARS], "page"
    if article.story_text:
        return html_to_text(article.story_text)[:MAX_CHARS], "story_text"
    return article.title, "title"
