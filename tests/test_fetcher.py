from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.fetcher import to_article_fields, upsert_articles
from app.hn_client import fetch_stories, get_hn_client
from app.main import app
from app.models import Article
from tests.hn_fakes import LINK_STORY, TEXT_STORY, fake_hn_client


def count_articles(engine) -> int:
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(Article))


def test_link_story_is_mapped_to_article_fields():
    fields = to_article_fields(LINK_STORY)

    assert fields["hn_id"] == 20985875  # converted from a string
    assert fields["created_at"] == datetime(2019, 9, 16, 16, 40, 8, tzinfo=timezone.utc)
    assert fields["url"] == "https://broadcast.listennotes.com/the-boring-technology"
    assert fields["story_text"] is None  # key missing in the response


def test_text_story_without_url_is_mapped():
    fields = to_article_fields(TEXT_STORY)

    assert fields["url"] is None
    assert fields["story_text"] == "I've been wondering about this for a while."


def test_client_asks_for_stories_only_newest_first():
    client = fake_hn_client([LINK_STORY])

    hits = fetch_stories(client, query="technology", limit=20)

    assert hits == [LINK_STORY]
    request = client.requests[0]
    assert request.url.path == "/api/v1/search_by_date"
    assert dict(request.url.params) == {
        "query": "technology",
        "tags": "story",
        "hitsPerPage": "20",
    }


def test_fetching_the_same_stories_twice_does_not_duplicate(engine):
    with Session(engine) as session:
        upsert_articles(session, [LINK_STORY, TEXT_STORY])
        upsert_articles(session, [LINK_STORY, TEXT_STORY])

    assert count_articles(engine) == 2


def test_refetched_story_is_updated(engine):
    with Session(engine) as session:
        upsert_articles(session, [LINK_STORY])
        upsert_articles(session, [{**LINK_STORY, "points": 2500, "num_comments": 500}])

    with Session(engine) as session:
        article = session.scalar(select(Article).where(Article.hn_id == 20985875))
    assert article.points == 2500
    assert article.num_comments == 500


def test_post_fetch_stores_stories_and_reports_count(api, engine):
    app.dependency_overrides[get_hn_client] = lambda: fake_hn_client(
        [LINK_STORY, TEXT_STORY]
    )

    response = api.post("/fetch")

    assert response.status_code == 200
    assert response.json() == {"fetched": 2}
    assert count_articles(engine) == 2


def test_post_fetch_returns_502_when_hacker_news_fails(api, engine):
    app.dependency_overrides[get_hn_client] = lambda: fake_hn_client([], status_code=503)

    response = api.post("/fetch")

    assert response.status_code == 502
    assert count_articles(engine) == 0


def test_malformed_stories_are_skipped_and_the_rest_are_stored(engine, caplog):
    no_author = {k: v for k, v in LINK_STORY.items() if k != "author"} | {"objectID": "1"}
    no_title = {**LINK_STORY, "objectID": "2", "title": None}
    bad_date = {**LINK_STORY, "objectID": "3", "created_at": "yesterday"}
    bad_id = {**LINK_STORY, "objectID": "not-a-number"}

    with Session(engine) as session:
        stored = upsert_articles(session, [no_author, no_title, bad_date, bad_id, TEXT_STORY])

    assert stored == 1
    assert count_articles(engine) == 1
    assert caplog.text.count("Skipping") == 4


def test_stories_with_wrongly_typed_values_are_skipped_and_the_rest_are_stored(engine, caplog):
    # Each of these maps without an error but could not be stored in its column.
    bad_points = {**LINK_STORY, "objectID": "1", "points": {"total": 5}}
    text_points = {**LINK_STORY, "objectID": "2", "points": "five"}
    bool_comments = {**LINK_STORY, "objectID": "3", "num_comments": True}
    list_title = {**LINK_STORY, "objectID": "4", "title": ["a", "b"]}
    number_url = {**LINK_STORY, "objectID": "5", "url": 12345}
    object_text = {**LINK_STORY, "objectID": "6", "story_text": {"html": "x"}}

    with Session(engine) as session:
        stored = upsert_articles(
            session,
            [bad_points, text_points, bool_comments, list_title, number_url, object_text, TEXT_STORY],
        )

    assert stored == 1  # only the good story
    assert count_articles(engine) == 1
    assert caplog.text.count("Skipping malformed story") == 6
