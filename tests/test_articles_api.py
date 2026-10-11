from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.models import Article

FIRST_DAY = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def articles(engine) -> list[int]:
    """25 articles, one per day; returns their ids from oldest to newest."""
    with Session(engine) as session:
        rows = [
            Article(
                hn_id=1000 + n,
                title=f"Story {n}",
                url=f"https://example.com/{n}",
                author="someone",
                points=n,
                num_comments=0,
                created_at=FIRST_DAY + timedelta(days=n),
            )
            for n in range(25)
        ]
        session.add_all(rows)
        session.commit()
        return [row.id for row in rows]


def test_first_page_has_newest_articles_first(api, articles):
    body = api.get("/articles").json()

    assert body["total"] == 25
    assert body["page"] == 1
    assert body["size"] == 10
    assert [item["title"] for item in body["items"]] == [
        f"Story {n}" for n in range(24, 14, -1)
    ]


def test_second_page_continues_where_the_first_ended(api, articles):
    body = api.get("/articles", params={"page": 2, "size": 10}).json()

    assert [item["title"] for item in body["items"]] == [
        f"Story {n}" for n in range(14, 4, -1)
    ]


def test_last_page_is_partial(api, articles):
    body = api.get("/articles", params={"page": 3, "size": 10}).json()

    assert len(body["items"]) == 5


def test_page_past_the_end_is_empty_not_an_error(api, articles):
    response = api.get("/articles", params={"page": 99})

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 25


@pytest.mark.parametrize("params", [{"page": 0}, {"size": 0}, {"size": 101}, {"page": "x"}])
def test_invalid_paging_is_rejected(api, params):
    assert api.get("/articles", params=params).status_code == 422


def test_get_article_returns_its_fields(api, articles):
    response = api.get(f"/articles/{articles[3]}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == articles[3]
    assert body["hn_id"] == 1003
    assert body["title"] == "Story 3"
    assert body["story_text"] is None
    assert body["created_at"] == "2026-01-04T00:00:00Z"


def test_get_missing_article_returns_404(api, articles):
    response = api.get("/articles/999999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Article not found"}
