import redis
from fastapi.testclient import TestClient

from app.cache import get_redis
from app.db import get_session
from app.main import app


def test_health_returns_ok():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_is_ok_when_the_database_answers(api):
    response = api.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


class BrokenSession:
    """Stands in for a database session whose connection is dead."""

    def execute(self, *args, **kwargs):
        raise RuntimeError("connection to server at 10.0.0.5 refused")


def use_broken_database():
    def broken_session():
        yield BrokenSession()

    app.dependency_overrides[get_session] = broken_session


def test_ready_is_503_when_the_database_is_down_and_hides_the_cause(api):
    use_broken_database()

    response = api.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Not ready"}  # the address stays in the server log


def test_health_stays_ok_when_the_database_is_down(api):
    use_broken_database()

    assert api.get("/health").status_code == 200


def test_ready_does_not_depend_on_redis(api):
    app.dependency_overrides[get_redis] = lambda: redis.Redis.from_url(
        "redis://127.0.0.1:6390/0", socket_connect_timeout=0.2
    )

    assert api.get("/ready").status_code == 200
