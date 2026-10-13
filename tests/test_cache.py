from dataclasses import replace

import redis
from sqlalchemy.orm import Session

from app.cache import get_redis, summary_fingerprint, summary_key
from app.content import get_page_client
from app.main import app
from app.summarizer import Summarizer, SummarizerError, get_summarizer
from app.models import Article
from tests.test_summary import fake_page_client, make_article, saved_article  # noqa: F401


class CountingSummarizer(Summarizer):
    """Remembers how many times it was asked."""

    def __init__(self):
        self.calls = 0

    def summarize(self, title: str, text: str) -> str:
        self.calls += 1
        return f"summary number {self.calls}"


def key_of(article_id: int) -> str:
    """The cache key of the article the saved_article fixture stores."""
    article = make_article()
    fingerprint = summary_fingerprint(article.title, article.url, article.story_text)
    return summary_key(article_id, fingerprint)


def use(summarizer: Summarizer) -> None:
    app.dependency_overrides[get_page_client] = lambda: fake_page_client({})
    app.dependency_overrides[get_summarizer] = lambda: summarizer


def test_second_request_is_served_from_the_cache(api, saved_article):
    summarizer = CountingSummarizer()
    use(summarizer)

    first = api.get(f"/articles/{saved_article}/summary").json()
    second = api.get(f"/articles/{saved_article}/summary").json()

    assert summarizer.calls == 1  # the second request never reached it
    assert first["cached"] is False
    assert second["cached"] is True
    assert second["summary"] == first["summary"] == "summary number 1"
    assert second["source"] == first["source"]


def test_cached_summary_expires(api, cache, saved_article):
    use(CountingSummarizer())

    api.get(f"/articles/{saved_article}/summary")

    ttl = cache.ttl(key_of(saved_article))
    assert 0 < ttl <= 86400  # -1 would mean "never expires"


def test_failed_summary_is_not_cached(api, cache, saved_article):
    class BrokenSummarizer(Summarizer):
        def summarize(self, title: str, text: str) -> str:
            raise SummarizerError("AI API is down")

    use(BrokenSummarizer())

    assert api.get(f"/articles/{saved_article}/summary").status_code == 502
    assert cache.exists(key_of(saved_article)) == 0


def test_service_works_when_redis_is_down(api, saved_article):
    summarizer = CountingSummarizer()
    use(summarizer)
    # Nothing listens on this port.
    app.dependency_overrides[get_redis] = lambda: redis.Redis.from_url(
        "redis://127.0.0.1:6390/0", socket_connect_timeout=0.2
    )

    first = api.get(f"/articles/{saved_article}/summary")
    second = api.get(f"/articles/{saved_article}/summary")

    assert first.status_code == second.status_code == 200
    assert second.json()["cached"] is False
    assert summarizer.calls == 2  # no cache, so the work is done each time


# --- The key follows what the summary depends on -----------------------------


def test_summary_is_made_again_when_the_article_changes(api, engine, saved_article):
    summarizer = CountingSummarizer()
    use(summarizer)
    api.get(f"/articles/{saved_article}/summary")

    with Session(engine) as session:  # a later fetch updates the stored story
        session.get(Article, saved_article).title = "Rust 2.0 released (updated)"
        session.commit()

    after_change = api.get(f"/articles/{saved_article}/summary").json()
    after_change_again = api.get(f"/articles/{saved_article}/summary").json()

    assert after_change["cached"] is False
    assert after_change["summary"] == "summary number 2"
    assert after_change_again["cached"] is True  # the new summary is cached in turn
    assert summarizer.calls == 2


def test_summary_is_made_again_when_the_summarizer_changes(api, saved_article, monkeypatch):
    summarizer = CountingSummarizer()
    use(summarizer)
    api.get(f"/articles/{saved_article}/summary")

    import app.cache

    monkeypatch.setattr(app.cache, "settings", replace(app.cache.settings, summarizer="gemini"))
    response = api.get(f"/articles/{saved_article}/summary").json()

    assert response["cached"] is False
    assert summarizer.calls == 2


def test_fingerprint_depends_on_every_input(monkeypatch):
    import app.cache

    base = summary_fingerprint("title", "https://a.example", "text")

    assert summary_fingerprint("title", "https://a.example", "text") == base
    assert summary_fingerprint("other", "https://a.example", "text") != base
    assert summary_fingerprint("title", "https://b.example", "text") != base
    assert summary_fingerprint("title", None, "text") != base
    assert summary_fingerprint("title", "https://a.example", None) != base

    settings = app.cache.settings
    monkeypatch.setattr(app.cache, "settings", replace(settings, summarizer="gemini"))
    gemini = summary_fingerprint("title", "https://a.example", "text")
    assert gemini != base  # another summarizer
    monkeypatch.setattr(
        app.cache, "settings", replace(settings, summarizer="gemini", gemini_model="other-model")
    )
    assert summary_fingerprint("title", "https://a.example", "text") != gemini  # another model
