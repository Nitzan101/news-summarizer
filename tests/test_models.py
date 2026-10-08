from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Article


def make_article(**overrides) -> Article:
    fields = dict(
        hn_id=8863,
        title="My YC app: Dropbox",
        url="http://www.getdropbox.com/u/2/screencast.html",
        author="dhouston",
        points=104,
        num_comments=71,
        created_at=datetime(2007, 4, 4, 19, 16, 40, tzinfo=timezone.utc),
    )
    fields.update(overrides)
    return Article(**fields)


def test_article_is_saved_and_read_back(engine):
    with Session(engine) as session:
        article = make_article()
        session.add(article)
        session.commit()
        article_id = article.id

    # A fresh session, so the read really goes to Postgres.
    with Session(engine) as session:
        loaded = session.get(Article, article_id)

    assert loaded.hn_id == 8863
    assert loaded.title == "My YC app: Dropbox"
    assert loaded.story_text is None
    assert loaded.fetched_at is not None  # filled in by Postgres


def test_duplicate_hn_id_is_rejected(engine):
    with Session(engine) as session:
        session.add(make_article())
        session.commit()

    with Session(engine) as session:
        session.add(make_article(title="Same story again"))
        with pytest.raises(IntegrityError):
            session.commit()
