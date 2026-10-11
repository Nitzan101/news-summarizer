"""Choosing the summarizer and starting the application."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
import app.summarizer as summarizer_module
from app.config import settings
from app.main import app
from app.scheduler import build_scheduler
from app.summarizer import (
    ClaudeSummarizer,
    GeminiSummarizer,
    MockSummarizer,
    build_summarizer,
)


@pytest.fixture
def configure(monkeypatch):
    """Run a test under different settings, restored afterwards."""

    def apply(**changes):
        monkeypatch.setattr(summarizer_module, "settings", replace(settings, **changes))
        build_summarizer.cache_clear()

    yield apply
    build_summarizer.cache_clear()


def test_mock_is_selected_by_default_settings(configure):
    configure(summarizer="mock")

    assert isinstance(build_summarizer(), MockSummarizer)


def test_gemini_is_selected_with_its_model(configure):
    configure(summarizer="gemini", gemini_api_key="test-key", gemini_model="gemini-test")

    summarizer = build_summarizer()

    assert isinstance(summarizer, GeminiSummarizer)
    assert summarizer.model == "gemini-test"


def test_claude_is_selected_with_its_model(configure):
    configure(summarizer="claude", anthropic_api_key="test-key", anthropic_model="claude-test")

    summarizer = build_summarizer()

    assert isinstance(summarizer, ClaudeSummarizer)
    assert summarizer.model == "claude-test"


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"summarizer": "gemini", "gemini_api_key": ""}, "GEMINI_API_KEY"),
        ({"summarizer": "claude", "anthropic_api_key": ""}, "ANTHROPIC_API_KEY"),
        ({"summarizer": "chatgpt"}, "Unknown SUMMARIZER"),
    ],
)
def test_misconfigured_summarizer_is_refused(configure, changes, message):
    configure(**changes)

    with pytest.raises(ValueError, match=message):
        build_summarizer()


def test_application_refuses_to_start_with_a_misconfigured_summarizer(configure, monkeypatch):
    configure(summarizer="gemini", gemini_api_key="")
    created = []
    monkeypatch.setattr(main_module, "init_db", lambda: created.append("tables"))

    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        with TestClient(app):  # entering the client runs the startup code
            pass

    assert created == []  # stopped before touching the database


def test_application_startup_creates_the_tables(configure, monkeypatch):
    configure(summarizer="mock")
    created = []
    monkeypatch.setattr(main_module, "init_db", lambda: created.append("tables"))

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

    assert created == ["tables"]


def test_startup_fetch_is_not_skipped_when_startup_is_slow():
    [job] = build_scheduler().get_jobs()

    # None = run however late; the default would drop a run that is 1 s overdue.
    assert job.misfire_grace_time is None


def test_api_documentation_lists_the_error_responses():
    paths = app.openapi()["paths"]

    assert "404" in paths["/articles/{article_id}"]["get"]["responses"]
    assert {"404", "502"} <= paths["/articles/{article_id}/summary"]["get"]["responses"].keys()
    assert "502" in paths["/fetch"]["post"]["responses"]
