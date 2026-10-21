from __future__ import annotations

import gzip

from radar.platform.models import HttpResponse
from radar.platform.adapters.sitemap import discover_and_collect
from radar.sitemap_urls import normalize_url


def _urlset(*urls: str) -> bytes:
    entries = "".join(f"<url><loc>{url}</loc></url>" for url in urls)
    return f"<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>{entries}</urlset>".encode()


def _index(*urls: str) -> bytes:
    entries = "".join(f"<sitemap><loc>{url}</loc></sitemap>" for url in urls)
    return f"<sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>{entries}</sitemapindex>".encode()


class FakeHttp:
    def __init__(self, pages: dict[str, tuple[int, bytes]]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def request(self, method: str, url: str, *, headers: dict[str, str] | None = None) -> HttpResponse:
        assert method == "GET"
        self.calls.append(url)
        status, body = self.pages.get(url, (404, b""))
        return HttpResponse(status, {}, body)


SITE = {"host": "example.com", "homepage_url": "https://example.com/", "sitemap_url": None}


def test_plain_sitemap_collects_normalized_same_host_urls() -> None:
    http = FakeHttp({
        "https://example.com/sitemap.xml": (200, _urlset(
            "https://EXAMPLE.com:443/Photo?Mode=AI#top",
            "https://example.com/Other",
        )),
    })

    result = discover_and_collect(SITE, http)

    assert result.status == "complete"
    assert result.urls == {"https://example.com/Photo?Mode=AI", "https://example.com/Other"}
    assert result.documents == 1
    assert normalize_url("HTTP://Example.COM:80/Case?X=1#part") == "http://example.com/Case?X=1"
    assert normalize_url("https://example.com/Case") != normalize_url("https://example.com/case")


def test_index_requires_every_shard_and_reads_gzip() -> None:
    http = FakeHttp({
        "https://example.com/sitemap.xml": (200, _index(
            "https://example.com/a.xml", "https://example.com/b.xml.gz"
        )),
        "https://example.com/a.xml": (200, _urlset("https://example.com/a")),
        "https://example.com/b.xml.gz": (200, gzip.compress(_urlset("https://example.com/b"))),
    })

    result = discover_and_collect(SITE, http)

    assert result.status == "complete"
    assert result.documents == 3
    assert result.urls == {"https://example.com/a", "https://example.com/b"}

    del http.pages["https://example.com/b.xml.gz"]
    incomplete = discover_and_collect(SITE, http)
    assert incomplete.status == "incomplete"
    assert incomplete.urls == set()


def test_robots_sitemap_declaration_disallow_and_crawl_delay() -> None:
    robot = b"User-agent: *\nCrawl-delay: 2\nSitemap: https://example.com/list.xml\n"
    http = FakeHttp({
        "https://example.com/robots.txt": (200, robot),
        "https://example.com/list.xml": (200, _index("https://example.com/part.xml")),
        "https://example.com/part.xml": (200, _urlset("https://example.com/a")),
    })
    waits: list[float] = []

    result = discover_and_collect(SITE, http, sleep=waits.append)

    assert result.status == "complete"
    assert result.urls == {"https://example.com/a"}
    assert waits and all(delay >= 2 for delay in waits)
    assert "https://example.com/sitemap.xml" not in http.calls

    blocked = FakeHttp({
        "https://example.com/robots.txt": (200, b"User-agent: *\nDisallow: /sitemap.xml\n"),
        "https://example.com/sitemap.xml": (200, _urlset("https://example.com/a")),
    })
    result = discover_and_collect(SITE, blocked)
    assert result.status == "incomplete"
    assert "https://example.com/sitemap.xml" not in blocked.calls


def test_empty_bad_xml_or_21_documents_is_incomplete() -> None:
    for body in (b"", b"not xml", b"<urlset/>", _urlset("https://elsewhere.com/a")):
        result = discover_and_collect(SITE, FakeHttp({"https://example.com/sitemap.xml": (200, body)}))
        assert result.status == "incomplete"
        assert result.urls == set()

    shards = [f"https://example.com/{i}.xml" for i in range(20)]
    http = FakeHttp({"https://example.com/sitemap.xml": (200, _index(*shards))})
    result = discover_and_collect(SITE, http)
    assert result.status == "incomplete"
    assert result.documents <= 20
    assert result.urls == set()


def test_oversized_gzip_or_more_than_20000_urls_is_incomplete() -> None:
    huge = gzip.compress(b"<urlset>" + b" " * (5 * 1024 * 1024 + 1) + b"</urlset>")
    result = discover_and_collect(SITE, FakeHttp({"https://example.com/sitemap.xml": (200, huge)}))
    assert result.status == "incomplete"

    many = _urlset(*(f"https://example.com/{i}" for i in range(20_001)))
    result = discover_and_collect(SITE, FakeHttp({"https://example.com/sitemap.xml": (200, many)}))
    assert result.status == "incomplete"
    assert result.urls == set()


def test_elapsed_budget_after_last_response_is_incomplete() -> None:
    elapsed = [0.0]

    class SlowHttp(FakeHttp):
        def request(self, method: str, url: str, *, headers: dict[str, str] | None = None) -> HttpResponse:
            response = super().request(method, url, headers=headers)
            if url.endswith("sitemap.xml"):
                elapsed[0] = 181.0
            return response

    http = SlowHttp({"https://example.com/sitemap.xml": (200, _urlset("https://example.com/a"))})
    result = discover_and_collect(SITE, http, clock=lambda: elapsed[0])
    assert result.status == "incomplete"
    assert result.urls == set()
