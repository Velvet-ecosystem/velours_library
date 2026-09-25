import json

import pytest

from velours_library.web_research import (
    GuardedWebFetcher,
    SearxngSearchProvider,
    WebResearchError,
    WebResearchPolicy,
    _GuardedRedirectHandler,
    sanitize_html,
    validate_external_url,
)


class FakeResponse:
    def __init__(
        self,
        payload,
        *,
        url="https://8.8.8.8/page",
        content_type="text/html; charset=utf-8",
        content_length=None,
    ):
        self.payload = payload
        self.url = url
        self.headers = {"Content-Type": content_type}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, amount=-1):
        if amount is None or amount < 0:
            return self.payload
        return self.payload[:amount]

    def geturl(self):
        return self.url


class FakeOpener:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append((request, timeout))
        return self.response


def test_url_policy_blocks_local_and_unsafe_targets():
    for target in (
        "file:///etc/passwd",
        "http://8.8.8.8/",
        "https://127.0.0.1/",
        "https://10.0.0.5/",
        "https://[::1]/",
        "https://user:pass@8.8.8.8/",
        "https://localhost/",
    ):
        with pytest.raises(WebResearchError):
            validate_external_url(target, resolve=False)
    assert (
        validate_external_url("https://8.8.8.8/path#frag", resolve=False)
        == "https://8.8.8.8/path"
    )


def test_sanitizer_keeps_reference_text_and_strips_active_content():
    raw = """
    <html><head><title>Useful Page</title><script>alert(1)</script></head>
    <body onload='bad()'><h1>Hello</h1><img src='https://evil.test/pixel'>
    <p onclick='bad()'>Readable <strong>text</strong>.</p>
    <form><input name='secret'></form>
    <a href='javascript:alert(1)'>bad link</a>
    <a href='https://8.8.8.8/more' style='color:red'>good link</a>
    </body></html>
    """
    rendered, text, title = sanitize_html(raw)
    assert title == "Useful Page"
    assert "alert(1)" not in rendered
    assert "<script" not in rendered
    assert "<form" not in rendered
    assert "<input" not in rendered
    assert "<img" not in rendered
    assert "onclick" not in rendered
    assert "style=" not in rendered
    assert "javascript:" not in rendered
    assert '<a href="https://8.8.8.8/more">' in rendered
    assert "Readable" in text and "text" in text


def test_fetcher_returns_bounded_sanitized_reference():
    payload = (
        b"<html><head><title>Example</title></head><body><h1>Hi</h1>"
        b"<script>bad()</script><p>Body text.</p></body></html>"
    )
    opener = FakeOpener(FakeResponse(payload))
    reference = GuardedWebFetcher(opener=opener).fetch("https://8.8.8.8/page")
    assert reference.title == "Example"
    assert reference.source == "8.8.8.8"
    assert reference.content_type == "text/html"
    assert "bad()" not in reference.html
    assert "Body text." in reference.text
    assert len(reference.content_sha256) == 64
    assert reference.byte_length == len(payload)
    assert reference.retrieved_at.endswith("Z")


def test_fetcher_rejects_wrong_type_and_oversize():
    wrong = GuardedWebFetcher(
        opener=FakeOpener(FakeResponse(b"{}", content_type="application/json"))
    )
    with pytest.raises(WebResearchError, match="content type"):
        wrong.fetch("https://8.8.8.8/page")

    policy = WebResearchPolicy(max_response_bytes=4)
    huge = GuardedWebFetcher(
        policy=policy,
        opener=FakeOpener(FakeResponse(b"12345", content_type="text/plain")),
    )
    with pytest.raises(WebResearchError, match="maximum"):
        huge.fetch("https://8.8.8.8/page")


def test_redirect_handler_blocks_private_target_and_limits_chain():
    policy = WebResearchPolicy(max_redirects=1)
    handler = _GuardedRedirectHandler(policy)
    from urllib.request import Request

    request = Request("https://8.8.8.8/start")
    with pytest.raises(WebResearchError):
        handler.redirect_request(
            request, None, 302, "", {}, "https://127.0.0.1/private"
        )
    first = handler.redirect_request(
        request, None, 302, "", {}, "https://1.1.1.1/next"
    )
    assert first is not None
    with pytest.raises(WebResearchError, match="redirect limit"):
        handler.redirect_request(first, None, 302, "", {}, "https://8.8.8.8/end")


def test_searxng_provider_is_bounded_and_reference_only():
    document = {
        "results": [
            {
                "title": "One",
                "url": "https://8.8.8.8/a",
                "content": "<b>summary one</b>",
            },
            {
                "title": "Local",
                "url": "https://127.0.0.1/private",
                "content": "blocked",
            },
            {
                "title": "Two",
                "url": "https://1.1.1.1/b",
                "content": "summary two",
            },
        ]
    }
    response = FakeResponse(
        json.dumps(document).encode("utf-8"),
        url="http://127.0.0.1:8888/search",
        content_type="application/json",
    )
    provider = SearxngSearchProvider(
        "http://127.0.0.1:8888/search",
        policy=WebResearchPolicy(max_results=2),
        opener=FakeOpener(response),
        allow_loopback_endpoint=True,
    )
    results = provider.search("velvet local ai")
    assert [item["title"] for item in results] == ["One", "Two"]
    assert results[0]["source"] == "8.8.8.8"
    assert results[0]["summary"] == "summary one"
    assert len(results[0]["result_id"]) == 20
