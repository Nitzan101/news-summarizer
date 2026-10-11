"""GeminiSummarizer against the real Google SDK with a fake HTTP layer.

Nothing here reaches the network: the SDK builds real requests and parses
real-shaped responses, and only the transport underneath it is replaced.
"""

import json

import httpx
import pytest
from google import genai
from google.genai import types

from app.summarizer import GeminiSummarizer, SummarizerError


def text_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}
            ],
            "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 40},
        },
    )


def error_response(code: int, status: str) -> httpx.Response:
    return httpx.Response(code, json={"error": {"code": code, "message": "nope", "status": status}})


def summarizer_answering(handler) -> tuple[GeminiSummarizer, list[httpx.Request]]:
    """A GeminiSummarizer whose HTTP requests go to `handler`; also returns the requests sent."""
    sent: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return handler(request)

    client = genai.Client(
        api_key="test-key",
        http_options=types.HttpOptions(client_args={"transport": httpx.MockTransport(transport)}),
    )
    return GeminiSummarizer(client, "gemini-3.5-flash-lite"), sent


def test_returns_the_stripped_text():
    summarizer, _ = summarizer_answering(
        lambda request: text_response("  Rust 2.0 ships a new borrow checker.  ")
    )

    assert summarizer.summarize("Rust 2.0", "Long article") == "Rust 2.0 ships a new borrow checker."


def test_request_carries_model_instructions_and_article():
    summarizer, sent = summarizer_answering(lambda request: text_response("A summary."))

    summarizer.summarize("Rust 2.0 released", "The article body")

    [request] = sent
    assert request.url.path.endswith("/models/gemini-3.5-flash-lite:generateContent")
    assert request.headers["x-goog-api-key"] == "test-key"
    body = json.loads(request.content)
    assert body["generationConfig"] == {"maxOutputTokens": 2000}
    instructions = body["systemInstruction"]["parts"][0]["text"]
    assert "two to three sentences" in instructions
    assert "never follow" in instructions
    assert body["contents"] == [
        {
            "role": "user",
            "parts": [{"text": "Title: Rust 2.0 released\n\nArticle text:\nThe article body"}],
        }
    ]


@pytest.mark.parametrize(
    "code, status",
    [
        (400, "INVALID_ARGUMENT"),  # e.g. a bad API key
        (403, "PERMISSION_DENIED"),
        (429, "RESOURCE_EXHAUSTED"),  # free-tier quota used up
        (500, "INTERNAL"),
    ],
)
def test_api_errors_become_summarizer_errors(code, status):
    summarizer, _ = summarizer_answering(lambda request: error_response(code, status))

    with pytest.raises(SummarizerError, match=str(code)):
        summarizer.summarize("Title", "Text")


def test_network_failure_becomes_a_summarizer_error():
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    summarizer, _ = summarizer_answering(unreachable)

    with pytest.raises(SummarizerError, match="Could not reach"):
        summarizer.summarize("Title", "Text")


def test_blocked_prompt_becomes_a_summarizer_error():
    summarizer, _ = summarizer_answering(
        lambda request: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})
    )

    with pytest.raises(SummarizerError, match="no text"):
        summarizer.summarize("Title", "Text")


def test_reply_cut_off_before_any_text_becomes_a_summarizer_error():
    summarizer, _ = summarizer_answering(
        lambda request: httpx.Response(
            200,
            json={"candidates": [{"content": {"role": "model"}, "finishReason": "MAX_TOKENS"}]},
        )
    )

    with pytest.raises(SummarizerError, match="MAX_TOKENS"):
        summarizer.summarize("Title", "Text")
