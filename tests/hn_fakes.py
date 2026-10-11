"""A stand-in for Hacker News: an HTTP client that answers from memory."""

import httpx

# Same shape as real responses from hn.algolia.com (checked 2026-10-11).
LINK_STORY = {
    "objectID": "20985875",
    "title": "The boring technology behind a one-person Internet company (2018)",
    "url": "https://broadcast.listennotes.com/the-boring-technology",
    "author": "mxschumacher",
    "points": 2010,
    "num_comments": 451,
    "created_at": "2019-09-16T16:40:08Z",
    # no story_text key at all, as in the real response
}
TEXT_STORY = {
    "objectID": "121003",
    "title": "Ask HN: The Arc Effect",
    "author": "tel",
    "points": 25,
    "num_comments": 16,
    "created_at": "2008-02-22T02:33:40Z",
    "story_text": "I've been wondering about this for a while.",
    # no url key: a text post
}


def fake_hn_client(hits: list[dict], status_code: int = 200) -> httpx.Client:
    """An httpx client that returns these hits instead of calling the network."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status_code, json={"hits": hits})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.requests = requests  # lets a test inspect what was sent
    return client
