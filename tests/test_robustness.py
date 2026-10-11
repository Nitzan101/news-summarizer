"""Bad input and misbehaving dependencies must produce a clear answer, never a 500."""

import httpx
import pytest

from app.cache import summary_key
from app.content import get_page_client, text_to_summarize
from app.hn_client import get_hn_client
from app.main import app
from app.summarizer import get_summarizer
from tests.test_cache import CountingSummarizer
from tests.test_summary import fake_page_client, make_article, saved_article  # noqa: F401


# --- Numbers too large for the database -------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/articles/99999999999",  # larger than a Postgres integer
        "/articles/99999999999/summary",
        "/articles?page=9223372036854775807&size=100",  # offset overflows a bigint
        "/articles?page=99999999999999999999",
    ],
)
def test_out_of_range_numbers_are_rejected(api, path):
    assert api.get(path).status_code == 422


def test_zero_and_negative_ids_are_rejected(api):
    assert api.get("/articles/0").status_code == 422
    assert api.get("/articles/-1/summary").status_code == 422


# --- Hacker News answering with something unexpected ------------------------


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>maintenance</html>"),  # not JSON at all
        httpx.Response(200, json={"message": "no hits here"}),  # JSON without the list
        httpx.Response(200, json={"hits": None}),
    ],
)
def test_fetch_returns_502_when_hacker_news_sends_an_unexpected_body(api, engine, response):
    app.dependency_overrides[get_hn_client] = lambda: httpx.Client(
        transport=httpx.MockTransport(lambda request: response)
    )

    result = api.post("/fetch")

    assert result.status_code == 502
    assert result.json() == {"detail": "Hacker News is unavailable"}


# --- A story whose link is not a usable URL ---------------------------------


def test_unusable_article_url_falls_back_to_the_story_text():
    too_long = "https://example.com/" + "a" * 70000  # httpx refuses to build this request
    article = make_article(url=too_long, story_text="The post itself")

    assert text_to_summarize(article, fake_page_client({})) == ("The post itself", "story_text")


# --- Garbage in the cache ----------------------------------------------------


@pytest.mark.parametrize("garbage", ["not json", '{"foo": 1}', "[]", '"just a string"'])
def test_unusable_cache_entry_is_ignored_and_replaced(api, cache, saved_article, garbage):
    summarizer = CountingSummarizer()
    app.dependency_overrides[get_page_client] = lambda: fake_page_client({})
    app.dependency_overrides[get_summarizer] = lambda: summarizer
    cache.set(summary_key(saved_article), garbage)

    response = api.get(f"/articles/{saved_article}/summary")

    assert response.status_code == 200
    assert response.json()["cached"] is False
    assert summarizer.calls == 1
    # The bad entry was overwritten with a good one.
    assert api.get(f"/articles/{saved_article}/summary").json()["cached"] is True
