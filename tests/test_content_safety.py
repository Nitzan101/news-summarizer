"""The page fetcher must not be usable to read our own network or to exhaust memory."""

import socket

import httpx
import pytest

from app import content
from app.content import MAX_PAGE_BYTES, fetch_page_text, is_public_http_url
from tests.test_summary import ARTICLE_PAGE, html_page

# Captured at import, before conftest's autouse fixture replaces it with "always True".
real_check = is_public_http_url
real_getaddrinfo = socket.getaddrinfo

PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def use_the_real_check(monkeypatch):
    monkeypatch.setattr(content, "is_public_http_url", real_check)


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    """Name lookups answer from this table; literal IPs still go through the real function."""
    table = {
        "localhost": ["127.0.0.1", "::1"],
        "internal.example": ["10.0.0.5"],
        "mixed.example": [PUBLIC_IP, "10.0.0.5"],
        "public.example": [PUBLIC_IP],
        "other.example": ["93.184.216.35"],
        "gone.example": None,
    }

    def getaddrinfo(host, port, *args, **kwargs):
        if host in table:
            if table[host] is None:
                raise socket.gaierror("no such host")
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in table[host]]
        return real_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


def recording_client(handler) -> tuple[httpx.Client, list[str]]:
    """A fake-network client, plus the list of URLs that were actually requested."""
    requested: list[str] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(wrapped)), requested


def redirect(to: str) -> httpx.Response:
    return httpx.Response(302, headers={"location": to})


# --- Which URLs count as public ---------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/secret",
        "http://[::1]/",
        "http://10.1.2.3/",
        "http://192.168.1.186/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::ffff:127.0.0.1]/",  # IPv4 loopback written as IPv6
        "http://localhost:8000/",
        "http://internal.example/",
        "http://mixed.example/",  # one private address is enough to refuse
        "http://gone.example/",  # does not resolve
        "https://user:password@public.example/",
        "ftp://public.example/",
        "file:///etc/passwd",
        "http:///nohost",
    ],
)
def test_internal_or_odd_urls_are_not_public(url):
    assert real_check(url) is False


@pytest.mark.parametrize("url", [f"http://{PUBLIC_IP}/", "https://public.example/page"])
def test_public_urls_are_allowed(url):
    assert real_check(url) is True


def test_an_internal_url_is_never_requested():
    client, requested = recording_client(lambda request: html_page(ARTICLE_PAGE))

    assert fetch_page_text(client, "http://127.0.0.1:8000/secret") is None
    assert requested == []


# --- Redirects --------------------------------------------------------------


def test_redirect_to_an_internal_address_is_blocked():
    def handler(request):
        return redirect("http://10.0.0.5/admin")

    client, requested = recording_client(handler)

    assert fetch_page_text(client, "https://public.example/start") is None
    assert requested == ["https://public.example/start"]  # the internal URL was never requested


def test_redirect_to_another_public_url_still_works():
    def handler(request):
        if request.url.host == "public.example":
            return redirect("https://other.example/final")  # absolute
        return html_page(ARTICLE_PAGE)

    client, requested = recording_client(handler)

    assert "Rust 2.0 was released today" in fetch_page_text(client, "https://public.example/a")
    assert requested == ["https://public.example/a", "https://other.example/final"]


def test_relative_redirect_is_resolved_against_the_current_url():
    def handler(request):
        if request.url.path == "/old":
            return redirect("/new")
        return html_page(ARTICLE_PAGE)

    client, requested = recording_client(handler)

    assert fetch_page_text(client, "https://public.example/old") is not None
    assert requested[-1] == "https://public.example/new"


def test_a_redirect_chain_longer_than_three_gives_up():
    client, requested = recording_client(lambda request: redirect("https://public.example/next"))

    assert fetch_page_text(client, "https://public.example/start") is None
    assert len(requested) == 4  # the first request plus three redirects, then stop


def test_three_redirects_are_still_followed():
    def handler(request):
        hops = {"/a": "/b", "/b": "/c", "/c": "/d"}
        if request.url.path in hops:
            return redirect(hops[request.url.path])
        return html_page(ARTICLE_PAGE)

    client, _ = recording_client(handler)

    assert fetch_page_text(client, "https://public.example/a") is not None


# --- Size and type limits ---------------------------------------------------


def test_a_page_larger_than_the_cap_gives_up():
    big = "<p>" + "x" * (MAX_PAGE_BYTES + 1) + "</p>"
    client, _ = recording_client(lambda request: html_page(big))

    assert fetch_page_text(client, "https://public.example/big") is None


def test_a_page_just_under_the_cap_is_read():
    body = "<p>" + "word " * 100 + "</p>"
    padding = "<!--" + "x" * (MAX_PAGE_BYTES - len(body) - 7) + "-->"
    client, _ = recording_client(lambda request: html_page(body + padding))

    assert fetch_page_text(client, "https://public.example/ok") is not None


class TrackedBody(httpx.SyncByteStream):
    """A response body that notes whether anyone read it."""

    def __init__(self):
        self.read = False

    def __iter__(self):
        self.read = True
        yield b"%PDF-1.7 " + b"x" * 1000


def test_a_non_html_response_is_rejected_without_reading_its_body():
    body = TrackedBody()
    response = httpx.Response(200, headers={"content-type": "application/pdf"}, stream=body)
    client, _ = recording_client(lambda request: response)

    assert fetch_page_text(client, "https://public.example/file.pdf") is None
    assert body.read is False


def test_a_normal_page_still_returns_its_text():
    client, _ = recording_client(lambda request: html_page(ARTICLE_PAGE))

    assert "Rust 2.0 was released today" in fetch_page_text(client, "https://public.example/rust")
