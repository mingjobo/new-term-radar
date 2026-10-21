from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from urllib.parse import urljoin, urlsplit

from .models import HttpResponse


class HttpError(RuntimeError):
    pass


class UnsafeUrl(HttpError):
    pass


class BudgetExceeded(HttpError):
    pass


Transport = Callable[[str, str, dict[str, str], bytes | None, float], HttpResponse]
Resolver = Callable[[str], Iterable[str]]


_PAID_HOSTS = {"api.aisa.one", "aisa.one", "api.goanyapi.com", "goanyapi.com"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _default_resolver(host: str) -> list[str]:
    return sorted({row[4][0] for row in socket.getaddrinfo(host, None)})


def _default_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
) -> HttpResponse:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        payload = response.read(5 * 1024 * 1024 + 1)
        if len(payload) > 5 * 1024 * 1024:
            raise HttpError("response exceeds 5 MiB limit")
        return HttpResponse(
            status=int(response.status),
            headers={key.lower(): value for key, value in response.headers.items()},
            body=payload,
        )


class HttpClient:
    def __init__(
        self,
        *,
        allowed_hosts: set[str],
        tick_limit: int = 200,
        source_limit: int = 60,
        timeout: float = 30.0,
        max_redirects: int = 5,
        transport: Transport | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        if tick_limit <= 0 or source_limit <= 0:
            raise ValueError("request limits must be positive")
        self.allowed_hosts = {host.casefold().rstrip(".") for host in allowed_hosts}
        self.tick_limit = tick_limit
        self.source_limit = source_limit
        self.timeout = timeout
        self.max_redirects = max_redirects
        self._transport = transport or _default_transport
        self._resolver = resolver or _default_resolver
        self.tick_requests = 0
        self.source_requests = 0

    def _validate_url(self, url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            raise UnsafeUrl("only HTTP(S) URLs are allowed")
        if parsed.username is not None or parsed.password is not None:
            raise UnsafeUrl("URL credentials are not allowed")
        host = (parsed.hostname or "").casefold().rstrip(".")
        if not host:
            raise UnsafeUrl("URL must include a hostname")
        if host in _PAID_HOSTS or any(host.endswith(f".{paid}") for paid in _PAID_HOSTS):
            raise UnsafeUrl("paid provider URL is not allowed")
        if host not in self.allowed_hosts:
            raise UnsafeUrl(f"host is outside the allowlist: {host}")
        try:
            addresses = list(self._resolver(host))
        except OSError as exc:
            raise UnsafeUrl(f"hostname could not be resolved: {host}") from exc
        if not addresses:
            raise UnsafeUrl(f"hostname did not resolve: {host}")
        for value in addresses:
            address = ipaddress.ip_address(value)
            if (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_multicast
                or address.is_reserved
                or address.is_unspecified
            ):
                raise UnsafeUrl(f"hostname resolves to private or unsafe address: {value}")

    def _spend(self) -> None:
        if self.tick_requests >= self.tick_limit:
            raise BudgetExceeded("tick request budget exhausted")
        if self.source_requests >= self.source_limit:
            raise BudgetExceeded("source request budget exhausted")
        self.tick_requests += 1
        self.source_requests += 1

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> HttpResponse:
        current = url
        request_headers = dict(headers or {})
        for redirect_count in range(self.max_redirects + 1):
            self._validate_url(current)
            self._spend()
            response = self._transport(method.upper(), current, request_headers, body, self.timeout)
            normalized_headers = {key.lower(): value for key, value in response.headers.items()}
            response = HttpResponse(response.status, normalized_headers, response.body)
            if response.status not in {301, 302, 303, 307, 308}:
                return response
            location = response.headers.get("location")
            if not location:
                raise HttpError("redirect response is missing Location")
            if redirect_count >= self.max_redirects:
                raise HttpError("too many redirects")
            current = urljoin(current, location)
            if response.status == 303:
                method, body = "GET", None
        raise HttpError("too many redirects")
