"""Read a complete same-host Sitemap URL set, or report an incomplete read."""

from __future__ import annotations

import time
import zlib
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

from ...sitemap_urls import normalize_url
from ..http import HttpClient, HttpError


MAX_DOCUMENTS = 20
MAX_URLS = 20_000
MAX_BYTES = 5 * 1024 * 1024
MAX_SECONDS = 180.0
USER_AGENT = "new-term-radar"


@dataclass(frozen=True)
class SitemapResult:
    status: Literal["complete", "incomplete"]
    urls: set[str]
    documents: int
    error: str | None = None


def _tag(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _decode(body: bytes, content_encoding: str) -> bytes:
    if len(body) > MAX_BYTES:
        raise ValueError("Sitemap response exceeds 5 MiB")
    if content_encoding.casefold() == "gzip" or body[:2] == b"\x1f\x8b":
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
        output = inflater.decompress(body, MAX_BYTES + 1)
        if len(output) > MAX_BYTES or not inflater.eof or inflater.unused_data:
            raise ValueError("Sitemap gzip is incomplete or exceeds 5 MiB")
        return output
    return body


def _parse(body: bytes) -> tuple[str, list[str]]:
    if b"<!doctype" in body.lower() or b"<!entity" in body.lower():
        raise ValueError("Sitemap DTD and entities are not allowed")
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise ValueError("invalid Sitemap XML") from exc
    kind = _tag(root.tag)
    if kind not in {"urlset", "sitemapindex"}:
        raise ValueError("unknown Sitemap XML root")
    item_name = "url" if kind == "urlset" else "sitemap"
    locations = [
        child.text.strip()
        for item in root
        if _tag(item.tag) == item_name
        for child in item
        if _tag(child.tag) == "loc" and child.text and child.text.strip()
    ]
    if not locations:
        raise ValueError("Sitemap has no URLs")
    return kind, locations


def _same_host(url: str, host: str) -> str:
    normalized = normalize_url(url)
    if urlsplit(normalized).hostname != host:
        raise ValueError("Sitemap contains an off-host URL")
    return normalized


def discover_and_collect(
    site: Mapping[str, Any],
    http: HttpClient,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> SitemapResult:
    """Return no URLs unless every required Sitemap document was read successfully."""
    documents = 0
    started = clock()
    try:
        host = str(site["host"]).casefold().rstrip(".")
        homepage = _same_host(str(site["homepage_url"]), host)
        scheme = urlsplit(homepage).scheme
        origin = f"{scheme}://{host}"
        robots_url = f"{origin}/robots.txt"
        robots_response = http.request("GET", robots_url, headers={"User-Agent": USER_AGENT})
        parser = RobotFileParser()
        if robots_response.status == 200:
            robots_body = _decode(robots_response.body, robots_response.headers.get("content-encoding", ""))
            parser.parse(robots_body.decode("utf-8", "replace").splitlines())
        elif robots_response.status in {404, 410}:
            parser.parse([])
        else:
            raise ValueError(f"robots.txt returned HTTP {robots_response.status}")
        delay = parser.crawl_delay(USER_AGENT) or 0
        if delay > 30:
            raise ValueError("robots.txt crawl delay exceeds the run budget")
        configured = site.get("sitemap_url")
        roots = [configured] if configured else (parser.site_maps() or [f"{origin}/sitemap.xml"])
        queue = deque(_same_host(str(url), host) for url in roots)
        seen_docs: set[str] = set()
        urls: set[str] = set()
        while queue:
            if clock() - started > MAX_SECONDS:
                raise ValueError("Sitemap run exceeded time budget")
            url = queue.popleft()
            if url in seen_docs:
                continue
            if len(seen_docs) >= MAX_DOCUMENTS:
                raise ValueError("Sitemap has more than 20 documents")
            if not parser.can_fetch(USER_AGENT, url):
                raise ValueError("robots.txt disallows a required Sitemap")
            if delay:
                sleep(float(delay))
            response = http.request(
                "GET", url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
            )
            documents += 1
            if clock() - started > MAX_SECONDS:
                raise ValueError("Sitemap run exceeded time budget")
            if response.status != 200:
                raise ValueError(f"Sitemap returned HTTP {response.status}")
            body = _decode(response.body, response.headers.get("content-encoding", ""))
            kind, locations = _parse(body)
            seen_docs.add(url)
            if kind == "sitemapindex":
                queue.extend(_same_host(child, host) for child in locations)
            else:
                urls.update(_same_host(page, host) for page in locations)
                if len(urls) > MAX_URLS:
                    raise ValueError("Sitemap has more than 20,000 URLs")
        if not urls:
            raise ValueError("Sitemap produced no page URLs")
        return SitemapResult("complete", urls, documents)
    except (HttpError, ValueError, KeyError, OSError, zlib.error) as exc:
        return SitemapResult("incomplete", set(), documents, str(exc)[:200])
