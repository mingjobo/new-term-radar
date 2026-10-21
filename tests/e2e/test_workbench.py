from __future__ import annotations

import hashlib
import socket
import threading
import uuid
from datetime import date, datetime
from wsgiref.simple_server import WSGIRequestHandler, make_server
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import sync_playwright

from radar.platform.web import create_app


TERM_ID = "00000000-0000-0000-0000-000000000101"
SITE_ID = "00000000-0000-0000-0000-000000000202"


class WorkbenchData:
    def __init__(self) -> None:
        self.daily_mode = "normal"
        self.events_empty = False
        self.sites = [{
            "id": SITE_ID, "name": "AI Photo Editor", "host": "aiphotoeditor.com",
            "homepage_url": "https://aiphotoeditor.com/", "sitemap_url": None,
            "enabled": True, "status": "baseline", "url_count": 139,
            "last_success_at": "2026-10-21T09:45:00+00:00", "last_attempt_at": "2026-10-21T09:45:00+00:00",
            "added_urls": 0, "removed_urls": 0,
        }]

    def overview(self, day, now):
        values = (2, 5, 1, 3, 1) if day == date(2026, 10, 20) else (1, 2, 0, 0, 0)
        return dict(zip(("new_terms", "evidence", "changed_sites", "added_urls", "removed_urls"), values)) | {"date": day.isoformat()}

    def daily_terms(self, day, *, cursor=None, limit=50):
        return {
            "date": day.isoformat(),
            "items": [] if self.daily_mode != "normal" or day != datetime.now(ZoneInfo("Asia/Shanghai")).date() else [{
                "id": TERM_ID, "name": "<img src=x onerror=alert(1)>", "kind": "name",
                "first_seen_at": "2026-10-21T09:00:00+00:00",
                "sources": ["github:breakout", "hf:models"], "evidence_count": 2,
                "url": "javascript:alert(1)",
            }],
            "next_cursor": None,
            "summary": {"status": self.daily_mode if self.daily_mode != "normal" else "ok",
                        "new_terms": 0 if self.daily_mode != "normal" else 1,
                        "evidence": 0 if self.daily_mode != "normal" else 2,
                        "last_success_at": "2026-10-21T09:05:00+00:00"},
        }

    def term(self, term_id):
        return {
            "id": term_id, "name": "<img src=x onerror=alert(1)>", "kind": "name", "language": "en",
            "canonical_key": "name:example", "first_seen_at": "2026-10-21T09:00:00+00:00",
            "last_seen_at": "2026-10-21T09:05:00+00:00",
            "evidence": [{"source_instance": "github:breakout", "observed_at": "2026-10-21T09:00:00+00:00", "url": "https://github.com/example", "excerpt": "Evidence", "metrics": {}}],
        }

    def competitor_sites(self, filters, *, page=1, limit=20):
        items = [site for site in self.sites if filters.get("q", "").lower() in site["name"].lower()]
        return {"items": items, "total": len(items), "page": page, "page_size": limit,
                "summary": {"sites": len(self.sites), "added_urls": 1, "removed_urls": 1, "abnormal_sites": 0}}

    def competitor_events(self, site_id, filters, *, page=1, limit=50):
        items = [{
            "id": str(uuid.uuid4()), "event_type": "added", "url": "https://aiphotoeditor.com/very/long/path/with-a-word-that-never-breaks-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "path": "/very/long/path/with-a-word-that-never-breaks-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "discovered_at": "2026-10-21T09:00:00+00:00",
        }, {
            "id": str(uuid.uuid4()), "event_type": "removed", "url": "https://aiphotoeditor.com/old-page",
            "path": "/old-page", "discovered_at": "2026-10-21T09:01:00+00:00",
        }]
        if self.events_empty:
            items = []
        return {"site": self.sites[0], "items": items, "total": len(items), "page": page, "page_size": limit}

    def settings_status(self, now):
        return {
            "sources": [
                {"source_instance": name, "status": "ok", "snapshot_items": size,
                 "last_success_at": "2026-10-21T09:00:00+00:00", "new_terms_last_run": 3}
                for name, size in (("github:breakout", 246), ("hf:models", 100), ("hf:spaces", 100))
            ],
            "sites": self.sites,
        }

    def add_site(self, name, homepage_url, sitemap_url):
        site_id = str(uuid.uuid4())
        self.sites.append({
            "id": site_id, "name": name, "host": "example.org", "homepage_url": homepage_url,
            "sitemap_url": sitemap_url, "enabled": True, "status": "not_collected",
            "url_count": None, "last_success_at": None, "last_attempt_at": None,
            "added_urls": 0, "removed_urls": 0,
        })
        return uuid.UUID(site_id)

    def update_site(self, site_id, *, name, sitemap_url, enabled):
        site = next(item for item in self.sites if item["id"] == str(site_id))
        site.update(name=name, sitemap_url=sitemap_url, enabled=enabled, status="not_collected" if enabled else "paused")


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass


@pytest.fixture(scope="module")
def server():
    data = WorkbenchData()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    app = create_app(
        data, username="tester", password_sha256=hashlib.sha256(b"password").hexdigest(),
        site_admin=data, allowed_origins={origin},
    )
    httpd = make_server("127.0.0.1", port, app, handler_class=QuietHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield origin, data
    httpd.shutdown()
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(channel="chrome", headless=True)
        yield instance
        instance.close()


@pytest.fixture
def page(browser, server):
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        http_credentials={"username": "tester", "password": "password"},
    )
    page = context.new_page()
    page.goto(server[0], wait_until="networkidle")
    yield page
    context.close()


def test_sidebar_and_tabs_exact_labels(page) -> None:
    assert page.locator("#primary-nav a").all_text_contents() == ["总览", "关键词看板", "设置"]
    page.get_by_role("link", name="关键词看板").click()
    assert page.locator("#board-tabs button").all_text_contents() == ["新词", "竞品"]
    assert page.locator("#content").get_by_text("关键词看板", exact=True).count() == 0


def test_overview_date_changes_five_values(page) -> None:
    page.locator("#overview-date").fill("2026-10-20")
    page.locator("#overview-date").dispatch_event("change")
    page.wait_for_function("document.querySelector('[data-metric=new_terms]')?.textContent === '2'")
    assert [page.locator(f"[data-metric={key}]").inner_text() for key in (
        "new_terms", "evidence", "changed_sites", "added_urls", "removed_urls"
    )] == ["2", "5", "1", "3", "1"]


def test_daily_terms_actions_and_no_baselines(page) -> None:
    page.get_by_role("link", name="关键词看板").click()
    page.locator(".term-row").first.wait_for()
    assert page.get_by_text("<img src=x onerror=alert(1)>").count() == 1
    assert page.locator("#content img").count() == 0
    assert "基线" not in page.locator("#content").inner_text()
    assert "SOURCE PULSE" not in page.locator("#content").inner_text()
    assert page.get_by_role("link", name="研究卡 →").get_attribute("href") == f"/terms/{TERM_ID}"
    assert page.get_by_text("链接已拦截").count() == 1
    page.get_by_role("link", name="研究卡 →").click()
    assert page.get_by_text("Evidence", exact=True).count() == 1


def test_competitor_sites_then_url_rows(page) -> None:
    page.get_by_role("link", name="关键词看板").click()
    page.get_by_role("button", name="竞品", exact=True).click()
    page.locator(".site-row").first.wait_for()
    assert page.get_by_text("AI Photo Editor").count() >= 1
    page.get_by_role("button", name="查看页面", exact=True).click()
    page.locator(".event-row").first.wait_for()
    assert page.get_by_text("移出站点地图").count() >= 1
    assert page.get_by_text("/old-page").count() >= 1
    assert page.get_by_role("link", name="打开原始页面").count() == 2
    assert page.locator(".event-row").count() == 2
    page.reload(wait_until="networkidle")
    assert page.get_by_role("button", name="竞品", exact=True).get_attribute("aria-pressed") == "true"


def test_settings_add_pause_resume_and_status(page) -> None:
    page.get_by_role("link", name="设置").click()
    page.locator(".settings-source-row").first.wait_for()
    assert page.get_by_text("246 项基线").count() == 1
    page.locator("#site-name").fill("New competitor")
    page.locator("#site-homepage").fill("https://example.org/")
    page.get_by_role("button", name="添加站点").click()
    page.get_by_text("New competitor").wait_for()
    row = page.locator(".settings-site-row").filter(has_text="New competitor")
    row.get_by_role("button", name="暂停").click()
    row.get_by_text("已暂停").wait_for()
    row.get_by_role("button", name="恢复").click()
    row.get_by_text("未采集").wait_for()


def test_narrow_layout_and_safe_external_text(page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.get_by_role("button", name="打开菜单").click()
    assert page.get_by_role("link", name="设置").is_visible()
    page.get_by_role("link", name="关键词看板").click()
    page.locator(".term-row").first.wait_for()
    assert page.locator("#content img").count() == 0


def test_empty_failed_and_no_match_states(page, server) -> None:
    data = server[1]
    try:
        data.daily_mode = "failed"
        page.goto(f"{server[0]}/#keywords/new", wait_until="networkidle")
        page.get_by_text("今日来源采集失败").wait_for()
        data.daily_mode = "ok"
        page.reload(wait_until="networkidle")
        page.get_by_text("今天暂无新词").wait_for()

        data.events_empty = True
        page.goto(f"{server[0]}/#keywords/competitors", wait_until="networkidle")
        page.locator(".site-row .status-text").first.wait_for()
        assert page.locator(".site-row .status-text").first.inner_text() == "首次建档"
        page.get_by_role("button", name="查看页面", exact=True).first.click()
        page.get_by_text("没有匹配的页面变化").wait_for()
        page.get_by_role("button", name="← 返回站点").click()
        page.get_by_placeholder("搜索站点").fill("not-a-real-site")
        page.get_by_role("button", name="筛选").click()
        page.get_by_text("没有匹配的站点").wait_for()
    finally:
        data.daily_mode = "normal"
        data.events_empty = False
