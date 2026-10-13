"""A summary request must not hold a database connection during the slow work.

The page download and the AI call can take up to 40 seconds. If the request kept
its connection from the pool (5 + 10 overflow) for that long, 15 slow requests
would leave every other request waiting for a connection.
"""

import httpx

from app.content import get_page_client
from app.main import app
from app.summarizer import MockSummarizer, get_summarizer
from tests.test_summary import ARTICLE_PAGE, saved_article  # noqa: F401


def test_database_connection_is_released_before_the_slow_work(api, engine, saved_article):
    checked_out_during: dict[str, int] = {}

    def page_handler(request: httpx.Request) -> httpx.Response:
        checked_out_during["page download"] = engine.pool.checkedout()
        return httpx.Response(200, headers={"content-type": "text/html"}, text=ARTICLE_PAGE)

    class WatchingSummarizer(MockSummarizer):
        def summarize(self, title: str, text: str) -> str:
            checked_out_during["summarizer"] = engine.pool.checkedout()
            return super().summarize(title, text)

    app.dependency_overrides[get_page_client] = lambda: httpx.Client(
        transport=httpx.MockTransport(page_handler)
    )
    app.dependency_overrides[get_summarizer] = lambda: WatchingSummarizer()

    response = api.get(f"/articles/{saved_article}/summary")

    assert response.status_code == 200
    assert response.json()["source"] == "page"  # the real page path was taken
    # Both steps ran, and at neither of them was a connection in use.
    assert checked_out_during == {"page download": 0, "summarizer": 0}


def test_unknown_article_does_not_keep_a_connection_either(api, engine):
    assert api.get("/articles/12345/summary").status_code == 404
    assert engine.pool.checkedout() == 0
