from __future__ import annotations

import pytest

from radar.platform.http import BudgetExceeded, HttpClient, UnsafeUrl
from radar.platform.models import HttpResponse


class StubTransport:
    def __init__(self, responses: list[HttpResponse] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[str] = []

    def __call__(self, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float) -> HttpResponse:
        self.calls.append(url)
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

    assert transport.calls == ["https://api.github.com/start"]


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
