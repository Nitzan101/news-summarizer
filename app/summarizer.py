"""Summarizers: one interface, interchangeable implementations."""

from abc import ABC, abstractmethod

from app.config import settings


class SummarizerError(Exception):
    """The summarizer could not produce a summary (e.g. the AI API failed)."""


class Summarizer(ABC):
    """What every summarizer can do, whatever is behind it."""

    @abstractmethod
    def summarize(self, title: str, text: str) -> str:
        """Return a short summary of the text."""


class MockSummarizer(Summarizer):
    """Stands in for a real AI model: no network, no cost, same answer every time."""

    MAX_CHARS = 200

    def summarize(self, title: str, text: str) -> str:
        excerpt = text[: self.MAX_CHARS].rstrip()
        if len(text) > self.MAX_CHARS:
            excerpt += "..."
        return f"[mock summary] {title}: {excerpt}"


def get_summarizer() -> Summarizer:
    """FastAPI dependency: the implementation selected by SUMMARIZER."""
    if settings.summarizer == "mock":
        return MockSummarizer()
    raise ValueError(f"Unknown SUMMARIZER: {settings.summarizer!r}")
