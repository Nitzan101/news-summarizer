from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy.orm import Session

from app.content import fetch_page_text, get_page_client, html_to_text, text_to_summarize
from app.main import app
from app.models import Article
from app.summarizer import MockSummarizer, Summarizer, SummarizerError, get_summarizer

ARTICLE_BODY = "Rust 2.0 was released today with a new borrow checker. " * 10
ARTICLE_PAGE = f"""
<html><head><title>News</title><style>body {{ color: red }}</style></head>
<body>
  <nav>Home | About | Login</nav>
  <article><h1>Rust 2.0</h1><p>{ARTICLE_BODY}</p></article>
  <script>trackVisitor()</script>
  <footer>Copyright 2026</footer>
</body></html>
"""


def fake_page_client(pages: dict[str, httpx.Response]) -> httpx.Client:
    """An HTTP client that serves these pages; any other URL fails to connect."""

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) not in pages:
            raise httpx.ConnectError("no such site", request=request)
        return pages[str(request.url)]

    return httpx.Client(transport=httpx.MockTransport(handler))


def html_page(html: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, html=html)


def make_article(**overrides) -> Article:
    fields = dict(
        hn_id=1,
        title="Rust 2.0 released",
        url="https://example.com/rust",
        author="someone",
        points=10,
        num_comments=2,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    fields.update(overrides)
    return Article(**fields)


# --- HTML to text -----------------------------------------------------------


def test_html_to_text_keeps_the_article_and_drops_page_chrome():
    text = html_to_text(ARTICLE_PAGE)

    assert "Rust 2.0 was released today" in text
    for noise in ("Login", "trackVisitor", "Copyright", "color: red"):
        assert noise not in text


def test_html_to_text_decodes_entities_and_tags_in_hn_story_text():
    story_text = "It is &quot;new&quot;:<p>https:&#x2F;&#x2F;example.com"

    assert html_to_text(story_text) == 'It is "new": https://example.com'


# --- Fetching a page --------------------------------------------------------


def test_fetch_page_text_returns_the_page_text():
    client = fake_page_client({"https://example.com/rust": html_page(ARTICLE_PAGE)})

    assert "Rust 2.0 was released today" in fetch_page_text(client, "https://example.com/rust")


@pytest.mark.parametrize(
    "response",
    [
        html_page("<p>Not found</p>", status_code=404),
        httpx.Response(200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"}),
        html_page("<p>Please log in</p>"),  # too short to be an article
    ],
)
def test_fetch_page_text_rejects_unusable_pages(response):
    client = fake_page_client({"https://example.com/rust": response})

    assert fetch_page_text(client, "https://example.com/rust") is None


def test_fetch_page_text_returns_none_when_the_site_is_down():
    assert fetch_page_text(fake_page_client({}), "https://example.com/rust") is None


def test_fetch_page_text_ignores_non_http_urls():
    assert fetch_page_text(fake_page_client({}), "file:///etc/passwd") is None


# --- Choosing what to summarize ---------------------------------------------


def test_linked_page_is_preferred():
    client = fake_page_client({"https://example.com/rust": html_page(ARTICLE_PAGE)})

    text, source = text_to_summarize(make_article(story_text="Some text"), client)

    assert source == "page"
    assert "Rust 2.0 was released today" in text


def test_falls_back_to_story_text_when_the_page_fails():
    article = make_article(story_text="Ask HN: <p>what changed?")

    assert text_to_summarize(article, fake_page_client({})) == (
        "Ask HN: what changed?",
        "story_text",
    )


def test_falls_back_to_title_when_there_is_nothing_else():
    article = make_article(url=None, story_text=None)

    assert text_to_summarize(article, fake_page_client({})) == ("Rust 2.0 released", "title")


def test_long_pages_are_capped():
    long_page = f"<p>{'word ' * 10000}</p>"
    client = fake_page_client({"https://example.com/rust": html_page(long_page)})

    text, _ = text_to_summarize(make_article(), client)

    assert len(text) == 8000


# --- Mock summarizer --------------------------------------------------------


def test_mock_summarizer_is_deterministic_and_marked_as_mock():
    summarizer = MockSummarizer()

    first = summarizer.summarize("Title", "Some text")

    assert first == "[mock summary] Title: Some text"
    assert first == summarizer.summarize("Title", "Some text")


# --- The endpoint -----------------------------------------------------------


@pytest.fixture
def saved_article(engine) -> int:
    with Session(engine) as session:
        article = make_article()
        session.add(article)
        session.commit()
        return article.id


def test_summary_endpoint_summarizes_the_linked_page(api, saved_article):
    app.dependency_overrides[get_page_client] = lambda: fake_page_client(
        {"https://example.com/rust": html_page(ARTICLE_PAGE)}
    )

    response = api.get(f"/articles/{saved_article}/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["article_id"] == saved_article
    assert body["source"] == "page"
    assert body["summary"].startswith("[mock summary] Rust 2.0 released: News Rust 2.0 Rust 2.0 was")


def test_summary_of_missing_article_returns_404(api, engine):
    assert api.get("/articles/999999/summary").status_code == 404


def test_summary_endpoint_returns_502_when_the_summarizer_fails(api, saved_article):
    class BrokenSummarizer(Summarizer):
        def summarize(self, title: str, text: str) -> str:
            raise SummarizerError("AI API is down")

    app.dependency_overrides[get_page_client] = lambda: fake_page_client({})
    app.dependency_overrides[get_summarizer] = lambda: BrokenSummarizer()

    response = api.get(f"/articles/{saved_article}/summary")

    assert response.status_code == 502
    assert response.json() == {"detail": "Summarizer is unavailable"}
