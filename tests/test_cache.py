import redis

from app.cache import get_redis, summary_key
from app.content import get_page_client
from app.main import app
from app.summarizer import Summarizer, SummarizerError, get_summarizer
from tests.test_summary import fake_page_client, saved_article  # noqa: F401


class CountingSummarizer(Summarizer):
    """Remembers how many times it was asked."""

    def __init__(self):
        self.calls = 0

    def summarize(self, title: str, text: str) -> str:
        self.calls += 1
        return f"summary number {self.calls}"


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

    ttl = cache.ttl(summary_key(saved_article))
    assert 0 < ttl <= 86400  # -1 would mean "never expires"


def test_failed_summary_is_not_cached(api, cache, saved_article):
    class BrokenSummarizer(Summarizer):
        def summarize(self, title: str, text: str) -> str:
            raise SummarizerError("AI API is down")

    use(BrokenSummarizer())

    assert api.get(f"/articles/{saved_article}/summary").status_code == 502
    assert cache.exists(summary_key(saved_article)) == 0


def test_service_works_when_redis_is_down(api, saved_article):
    summarizer = CountingSummarizer()
    use(summarizer)
    # Nothing listens on this port.
    app.dependency_overrides[get_redis] = lambda: redis.Redis.from_url(
        "redis://localhost:6390/0", socket_connect_timeout=0.2
    )

    first = api.get(f"/articles/{saved_article}/summary")
    second = api.get(f"/articles/{saved_article}/summary")

    assert first.status_code == second.status_code == 200
    assert second.json()["cached"] is False
    assert summarizer.calls == 2  # no cache, so the work is done each time
