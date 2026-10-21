from __future__ import annotations

import ipaddress
import http.client
import socket
import ssl
from collections.abc import Callable, Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit

from .models import HttpResponse


class HttpError(RuntimeError):
    pass


class UnsafeUrl(HttpError):
    pass


class BudgetExceeded(HttpError):
    pass


Transport = Callable[[str, str, dict[str, str], bytes | None, float, str], HttpResponse]
Resolver = Callable[[str], Iterable[str]]


_PAID_HOSTS = {"api.aisa.one", "aisa.one", "api.goanyapi.com", "goanyapi.com"}


def _default_resolver(host: str) -> list[str]:
    return sorted({row[4][0] for row in socket.getaddrinfo(host, None)})


def _default_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
    pinned_ip: str,
) -> HttpResponse:
    parsed = urlsplit(url)
    host = parsed.hostname
    if not host:
        raise UnsafeUrl("URL must include a hostname")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if parsed.scheme == "https":
        connection: http.client.HTTPConnection = http.client.HTTPSConnection(
            host, port, timeout=timeout, context=ssl.create_default_context()
        )
    else:
        connection = http.client.HTTPConnection(host, port, timeout=timeout)

    # http.client still uses the original host for Host and TLS SNI/certificate checks.
    # Only its socket destination is replaced with the IP validated by HttpClient.
    connection._create_connection = (  # type: ignore[method-assign]
        lambda address, timeout, source_address=None: socket.create_connection(
            (pinned_ip, address[1]), timeout, source_address
        )
    )
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        payload = response.read(5 * 1024 * 1024 + 1)
        if len(payload) > 5 * 1024 * 1024:
            raise HttpError("response exceeds 5 MiB limit")
        return HttpResponse(
            status=int(response.status),
            headers={key.lower(): value for key, value in response.getheaders()},
            body=payload,
        )
    except (OSError, http.client.HTTPException) as exc:
        raise HttpError(f"HTTP request failed: {type(exc).__name__}") from exc
    finally:
        connection.close()


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

    def _validate_url(self, url: str) -> str:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise UnsafeUrl("invalid HTTP(S) URL") from exc
        if parsed.scheme not in {"http", "https"}:
            raise UnsafeUrl("only HTTP(S) URLs are allowed")
        if parsed.username is not None or parsed.password is not None:
            raise UnsafeUrl("URL credentials are not allowed")
        host = (parsed.hostname or "").casefold().rstrip(".")
        if not host:
            raise UnsafeUrl("URL must include a hostname")
        if port is not None and port not in {80, 443}:
            raise UnsafeUrl("nonstandard URL ports are not allowed")
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
            try:
                address = ipaddress.ip_address(value)
            except ValueError as exc:
                raise UnsafeUrl("hostname resolved to an invalid IP address") from exc
            if not address.is_global:
                raise UnsafeUrl(f"hostname resolves to private or unsafe address: {value}")
        return str(ipaddress.ip_address(addresses[0]))

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
            pinned_ip = self._validate_url(current)
            self._spend()
            response = self._transport(method.upper(), current, request_headers, body, self.timeout, pinned_ip)
            normalized_headers = {key.lower(): value for key, value in response.headers.items()}
            response = HttpResponse(response.status, normalized_headers, response.body)
            if response.status not in {301, 302, 303, 307, 308}:
                return response
            location = response.headers.get("location")
            if not location:
                raise HttpError("redirect response is missing Location")
            if redirect_count >= self.max_redirects:
                raise HttpError("too many redirects")
            next_url = urljoin(current, location)
            current_parts = urlsplit(current)
            next_parts = urlsplit(next_url)
            if current_parts.scheme == "https" and next_parts.scheme == "http":
                raise UnsafeUrl("HTTPS redirect downgrade is not allowed")
            if current_parts.hostname != next_parts.hostname:
                request_headers = {
                    key: value
                    for key, value in request_headers.items()
                    if key.casefold() not in {"authorization", "cookie", "proxy-authorization"}
                }
            current = next_url
            if response.status == 303:
                method, body = "GET", None
        raise HttpError("too many redirects")
