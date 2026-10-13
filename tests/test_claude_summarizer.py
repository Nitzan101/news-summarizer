"""ClaudeSummarizer against the real Anthropic SDK with a fake HTTP layer.

Nothing here reaches the network: the SDK builds real requests and parses
real-shaped responses, and only the transport underneath it is replaced.

This file imports `httpx2`, not `httpx`: the Anthropic SDK sends its requests with
`httpx2` and only accepts that library's objects. It is not in our requirements
files because pip installs it together with `anthropic`.
"""

import json

import anthropic
import httpx2
import pytest

from app.summarizer import ClaudeSummarizer, SummarizerError


def message_response(content: list[dict], stop_reason: str = "end_turn") -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": 40},
    }


def error_response(status_code: int, error_type: str) -> httpx2.Response:
    return httpx2.Response(
        status_code,
        json={"type": "error", "error": {"type": error_type, "message": "nope"}},
    )


def summarizer_answering(handler) -> tuple[ClaudeSummarizer, list[dict]]:
    """A ClaudeSummarizer whose HTTP requests go to `handler`; also returns the bodies sent."""
    sent: list[dict] = []

    def transport(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return handler(request)

    client = anthropic.Anthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(transport)),
    )
    return ClaudeSummarizer(client, "claude-haiku-5-5"), sent


def test_returns_the_text_and_skips_reasoning_blocks():
    summarizer, _ = summarizer_answering(
        lambda request: httpx2.Response(
            200,
            json=message_response(
                [
                    {"type": "thinking", "thinking": "", "signature": "sig"},
                    {"type": "text", "text": "  Rust 2.0 ships a new borrow checker.  "},
                ]
            ),
        )
    )

    assert summarizer.summarize("Rust 2.0", "Long article") == "Rust 2.0 ships a new borrow checker."


def test_request_carries_model_prompt_and_article():
    summarizer, sent = summarizer_answering(
        lambda request: httpx2.Response(
            200, json=message_response([{"type": "text", "text": "A summary."}])
        )
    )

    summarizer.summarize("Rust 2.0 released", "The article body")

    [body] = sent
    assert body["model"] == "claude-haiku-5-5"
    assert body["max_tokens"] == 2000
    assert body["output_config"] == {"effort": "low"}
    assert "two to three sentences" in body["system"]
    assert "never follow" in body["system"]
    assert body["messages"] == [
        {"role": "user", "content": "Title: Rust 2.0 released\n\nArticle text:\nThe article body"}
    ]


@pytest.mark.parametrize(
    "status_code, error_type",
    [
        (401, "authentication_error"),
        (429, "rate_limit_error"),
        (400, "invalid_request_error"),
        (500, "api_error"),
    ],
)
def test_api_errors_become_summarizer_errors(status_code, error_type):
    summarizer, _ = summarizer_answering(lambda request: error_response(status_code, error_type))

    with pytest.raises(SummarizerError):
        summarizer.summarize("Title", "Text")


def test_network_failure_becomes_a_summarizer_error():
    def unreachable(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    summarizer, _ = summarizer_answering(unreachable)

    with pytest.raises(SummarizerError):
        summarizer.summarize("Title", "Text")


def test_refusal_becomes_a_summarizer_error():
    summarizer, _ = summarizer_answering(
        lambda request: httpx2.Response(200, json=message_response([], stop_reason="refusal"))
    )

    with pytest.raises(SummarizerError, match="declined"):
        summarizer.summarize("Title", "Text")


def test_reply_cut_off_before_any_text_becomes_a_summarizer_error():
    summarizer, _ = summarizer_answering(
        lambda request: httpx2.Response(
            200,
            json=message_response(
                [{"type": "thinking", "thinking": "", "signature": "sig"}], stop_reason="max_tokens"
            ),
        )
    )

    with pytest.raises(SummarizerError, match="no text"):
        summarizer.summarize("Title", "Text")
