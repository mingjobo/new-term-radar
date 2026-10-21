"""Narrow settings writer: site configuration only, never terms or URL events."""

from __future__ import annotations

import ipaddress
import socket
import uuid
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit
from uuid import UUID

from .db import connect, validate_schema_name


Resolver = Callable[[str], Iterable[str]]


def _resolve(host: str) -> list[str]:
    return sorted({row[4][0] for row in socket.getaddrinfo(host, None)})


def public_http_host(url: str, resolver: Resolver = _resolve) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid HTTP(S) URL") from exc
    host = (parsed.hostname or "").casefold().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError("only public HTTP(S) URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL credentials are not allowed")
    if port is not None and port not in {80, 443}:
        raise ValueError("nonstandard URL ports are not allowed")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("private hostnames are not allowed")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise ValueError("private IP addresses are not allowed")
    try:
        addresses = list(resolver(host))
    except OSError as exc:
        raise ValueError("site hostname could not be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("site hostname must resolve only to public IP addresses")
    return host


class SiteAdmin:
    def __init__(self, dsn: str, *, schema: str = "public", resolver: Resolver = _resolve) -> None:
        self.dsn = dsn
        self.schema = validate_schema_name(schema)
        self.resolver = resolver

    @staticmethod
    def _name(value: str) -> str:
        name = value.strip()
        if not 1 <= len(name) <= 200:
            raise ValueError("site name must be 1 to 200 characters")
        return name

    def _sitemap(self, value: str | None, host: str) -> str | None:
        if value is None or not value.strip():
            return None
        sitemap = value.strip()
        if public_http_host(sitemap, self.resolver) != host:
            raise ValueError("Sitemap URL must use the site's hostname")
        return sitemap

    def add_site(self, name: str, homepage_url: str, sitemap_url: str | None) -> UUID:
        clean_name = self._name(name)
        homepage = homepage_url.strip()
        host = public_http_host(homepage, self.resolver)
        sitemap = self._sitemap(sitemap_url, host)
        site_id = uuid.uuid4()
        with connect(self.dsn, schema=self.schema) as connection:
            connection.execute(
                "INSERT INTO radar_sites (id, name, homepage_url, host, sitemap_url) "
                "VALUES (%s, %s, %s, %s, %s)",
                (site_id, clean_name, homepage, host, sitemap),
            )
        return site_id

    def update_site(self, site_id: UUID, *, name: str, sitemap_url: str | None, enabled: bool) -> None:
        clean_name = self._name(name)
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        with connect(self.dsn, schema=self.schema) as connection:
            row = connection.execute("SELECT host FROM radar_sites WHERE id = %s", (site_id,)).fetchone()
            if row is None:
                raise ValueError("unknown site")
            sitemap = self._sitemap(sitemap_url, row["host"])
            connection.execute(
                "UPDATE radar_sites SET name = %s, sitemap_url = %s, enabled = %s, updated_at = now() "
                "WHERE id = %s",
                (clean_name, sitemap, enabled, site_id),
            )
