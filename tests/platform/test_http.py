from __future__ import annotations

import pytest

from radar.platform import http as http_module
from radar.platform.http import BudgetExceeded, HttpClient, UnsafeUrl
from radar.platform.models import HttpResponse


class StubTransport:
    def __init__(self, responses: list[HttpResponse] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float, pinned_ip: str) -> HttpResponse:
        self.calls.append((url, pinned_ip))
        if self.responses:
            return self.responses.pop(0)
        return HttpResponse(status=200, headers={}, body=b"ok")


@pytest.mark.parametrize(
    "url",
    [
        "https://api.aisa.one/v1/search",
        "https://api.goanyapi.com/v1/search",
        "https://127.0.0.1/data",
        "http://169.254.169.254/latest/meta-data",
        "file:///etc/passwd",
    ],
)
def test_paid_or_private_urls_are_rejected_without_a_request(url: str) -> None:
    transport = StubTransport()
    client = HttpClient(
        allowed_hosts={"api.github.com", "huggingface.co"},
        transport=transport,
        resolver=lambda _host: ["93.184.216.34"],
    )

    with pytest.raises(UnsafeUrl):
        client.request("GET", url)

    assert transport.calls == []


def test_hostname_resolving_to_private_address_is_rejected() -> None:
    transport = StubTransport()
    client = HttpClient(
        allowed_hosts={"api.github.com"},
        transport=transport,
        resolver=lambda _host: ["10.0.0.8"],
    )

    with pytest.raises(UnsafeUrl, match="private"):
        client.request("GET", "https://api.github.com/search/repositories")

    assert transport.calls == []


def test_redirect_must_stay_on_allowlist() -> None:
    transport = StubTransport([
        HttpResponse(status=302, headers={"location": "https://example.com/escape"}, body=b""),
    ])
    client = HttpClient(
        allowed_hosts={"api.github.com"},
        transport=transport,
        resolver=lambda _host: ["140.82.112.6"],
    )

    with pytest.raises(UnsafeUrl, match="allowlist"):
        client.request("GET", "https://api.github.com/start")

    assert transport.calls == [("https://api.github.com/start", "140.82.112.6")]


def test_tick_budget_rejects_request_201() -> None:
    transport = StubTransport()
    client = HttpClient(
        allowed_hosts={"api.github.com"},
        tick_limit=200,
        source_limit=500,
        transport=transport,
        resolver=lambda _host: ["140.82.112.6"],
    )

    for _ in range(200):
        client.request("GET", "https://api.github.com/rate_limit")
    with pytest.raises(BudgetExceeded, match="tick"):
        client.request("GET", "https://api.github.com/rate_limit")

    assert len(transport.calls) == 200


def test_source_budget_rejects_request_61() -> None:
    transport = StubTransport()
    client = HttpClient(
        allowed_hosts={"huggingface.co"},
        tick_limit=200,
        source_limit=60,
        transport=transport,
        resolver=lambda _host: ["13.35.32.52"],
    )

    for _ in range(60):
        client.request("GET", "https://huggingface.co/api/models")
    with pytest.raises(BudgetExceeded, match="source"):
        client.request("GET", "https://huggingface.co/api/models")

    assert len(transport.calls) == 60


def test_public_ip_pinned_across_redirects() -> None:
    transport = StubTransport([
        HttpResponse(302, {"location": "/second"}, b""),
    ])
    answers = iter((["93.184.216.34"], ["169.254.169.254"]))
    client = HttpClient(
        allowed_hosts={"example.com"},
        transport=transport,
        resolver=lambda _host: next(answers),
    )

    with pytest.raises(UnsafeUrl, match="private"):
        client.request("GET", "https://example.com/first")

    assert transport.calls == [("https://example.com/first", "93.184.216.34")]


def test_default_transport_connects_to_pinned_ip_with_original_tls_host(monkeypatch: pytest.MonkeyPatch) -> None:
    destinations: list[tuple[str, int]] = []
    hosts: list[str] = []

    class FakeResponse:
        status = 200

        def read(self, _limit: int) -> bytes:
            return b"ok"

        def getheaders(self) -> list[tuple[str, str]]:
            return []

    class FakeHTTPSConnection:
        def __init__(self, host: str, port: int, *, timeout: float, context: object) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout
            hosts.append(host)

        def request(self, method: str, path: str, *, body: bytes | None, headers: dict[str, str]) -> None:
            assert method == "GET"
            assert path == "/sitemap.xml"
            self._create_connection((self.host, self.port), self.timeout)

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            pass

    monkeypatch.setattr(http_module.http.client, "HTTPSConnection", FakeHTTPSConnection)
    monkeypatch.setattr(
        http_module.socket,
        "create_connection",
        lambda address, _timeout, _source_address=None: destinations.append(address),
    )
    client = HttpClient(
        allowed_hosts={"example.com"}, resolver=lambda _host: ["93.184.216.34"]
    )

    assert client.request("GET", "https://example.com/sitemap.xml").status == 200
    assert hosts == ["example.com"]
    assert destinations == [("93.184.216.34", 443)]


def test_redirect_does_not_forward_authorization_to_another_host() -> None:
    seen: list[dict[str, str]] = []

    def transport(method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float, pinned_ip: str) -> HttpResponse:
        seen.append(headers.copy())
        if len(seen) == 1:
            return HttpResponse(302, {"location": "https://huggingface.co/next"}, b"")
        return HttpResponse(200, {}, b"ok")

    client = HttpClient(
        allowed_hosts={"api.github.com", "huggingface.co"},
        transport=transport,
        resolver=lambda _host: ["93.184.216.34"],
    )
    assert client.request("GET", "https://api.github.com/start", headers={"Authorization": "secret"}).status == 200
    assert seen[0]["Authorization"] == "secret"
    assert all(key.casefold() != "authorization" for key in seen[1])


def test_https_redirect_to_http_is_rejected() -> None:
    transport = StubTransport([HttpResponse(302, {"location": "http://example.com/next"}, b"")])
    client = HttpClient(
        allowed_hosts={"example.com"},
        transport=transport,
        resolver=lambda _host: ["93.184.216.34"],
    )
    with pytest.raises(UnsafeUrl, match="downgrade"):
        client.request("GET", "https://example.com/start")
    assert len(transport.calls) == 1
