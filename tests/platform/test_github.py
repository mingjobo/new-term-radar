from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from radar_platform.adapters import github
from radar_platform.models import HttpResponse, PlatformConfig, SourceSnapshot


NOW = datetime(2026, 10, 15, 8, 17, tzinfo=timezone.utc)


class GithubHttp:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = list(pages)
        self.urls: list[str] = []

    def request(self, method: str, url: str, *, headers=None, body=None) -> HttpResponse:
        self.urls.append(url)
        payload = self.pages.pop(0)
        return HttpResponse(200, {"content-type": "application/json"}, json.dumps(payload).encode())


@pytest.fixture
def cfg() -> PlatformConfig:
    return PlatformConfig(
        sources={
            "github:breakout": {
                "enabled": True,
                "window_days": 14,
                "min_stars": 300,
                "velocity_min": 200,
                "delta_min": 400,
                "pages": 2,
            }
        },
        roots=[],
        aliases={},
        hf_task_map={},
        budgets={},
        timezone="Asia/Shanghai",
    )


def _repo(*, repo_id: int = 101, stars: int, age_hours: int, name: str = "Acme/Fast-Radar") -> dict:
    return {
        "id": repo_id,
        "full_name": name,
        "name": name.split("/", 1)[1],
        "html_url": f"https://github.com/{name}",
        "description": "An evidence-backed radar for emerging tools",
        "created_at": (NOW - timedelta(hours=age_hours)).isoformat().replace("+00:00", "Z"),
        "stargazers_count": stars,
    }


def _page(items: list[dict], *, total: int | None = None, incomplete: bool = False) -> dict:
    return {"total_count": len(items) if total is None else total, "incomplete_results": incomplete, "items": items}


def _observed(stars: int, hours_ago: int) -> dict:
    return {"observed_at": (NOW - timedelta(hours=hours_ago)).isoformat(), "stars": stars}


def test_fast_new_repo_is_discovered_with_real_identity_and_time(cfg: PlatformConfig) -> None:
    repo = _repo(stars=1000, age_hours=48)
    result = github.collect(
        cfg,
        SourceSnapshot(0, {}, None),
        NOW,
        GithubHttp([_page([repo])]),
        source_instance="github:breakout",
    )
    discoveries = [event for event in result.observations if event.is_discovery]

    assert len(discoveries) == 1
    event = discoveries[0]
    assert event.external_id == "101"
    assert event.entity_key == "name:github:breakout:101"
    assert event.url == "https://github.com/Acme/Fast-Radar"
    assert event.observed_at == NOW
    assert event.metrics["velocity_per_day"] == 500
    assert event.metrics["full_name"] == "Acme/Fast-Radar"


def test_eight_hour_gain_is_not_misreported_as_daily_delta(cfg: PlatformConfig) -> None:
    repo = _repo(stars=1000, age_hours=240)
    previous = SourceSnapshot(
        1,
        {"repos": {"101": [_observed(800, 8)]}, "flagged": {}},
        NOW - timedelta(hours=8),
    )

    result = github.collect(
        cfg, previous, NOW, GithubHttp([_page([repo])]), source_instance="github:breakout"
    )

    event = result.observations[0]
    assert event.is_discovery is False
    assert event.metrics["delta_24h"] is None
    assert event.metrics["velocity_per_day"] == 100


def test_nearest_observation_from_20_to_28_hours_drives_daily_delta(cfg: PlatformConfig) -> None:
    repo = _repo(stars=1300, age_hours=240)
    previous = SourceSnapshot(
        3,
        {
            "repos": {"101": [_observed(100, 50), _observed(850, 24), _observed(1100, 8)]},
            "flagged": {},
        },
        NOW - timedelta(hours=8),
    )

    result = github.collect(
        cfg, previous, NOW, GithubHttp([_page([repo])]), source_instance="github:breakout"
    )
    event = result.observations[0]

    assert event.is_discovery is True
    assert event.metrics["velocity_per_day"] == 130
    assert event.metrics["delta_24h"] == 450
    assert event.data_window["delta_observed_at"] == (NOW - timedelta(hours=24)).isoformat()


def test_snapshot_keeps_only_48_hours_and_same_slot_is_idempotent(cfg: PlatformConfig) -> None:
    repo = _repo(stars=1300, age_hours=240)
    previous = SourceSnapshot(
        2,
        {
            "repos": {"101": [_observed(10, 60), _observed(850, 24)]},
            "flagged": {},
        },
        NOW - timedelta(hours=8),
    )
    first = github.collect(cfg, previous, NOW, GithubHttp([_page([repo])]), source_instance="github:breakout")
    advanced = SourceSnapshot(3, first.next_snapshot, NOW)
    repeated = github.collect(cfg, advanced, NOW, GithubHttp([_page([repo])]), source_instance="github:breakout")

    history = repeated.next_snapshot["repos"]["101"]
    assert len(history) == 2
    assert all(datetime.fromisoformat(item["observed_at"]) >= NOW - timedelta(hours=48) for item in history)
    assert [event for event in repeated.observations if event.is_discovery] == []


@pytest.mark.parametrize(
    "payload",
    [
        _page([]),
        {"total_count": 1, "incomplete_results": False},
        _page([{"id": 1}]),
        _page([_repo(stars=1000, age_hours=48)], total=3),
        _page([_repo(stars=1000, age_hours=48)], incomplete=True),
    ],
)
def test_empty_changed_or_truncated_search_does_not_advance_snapshot(cfg: PlatformConfig, payload: dict) -> None:
    previous = SourceSnapshot(7, {"repos": {"keep": [_observed(3, 8)]}, "flagged": {}}, NOW)

    result = github.collect(
        cfg, previous, NOW, GithubHttp([payload]), source_instance="github:breakout"
    )

    assert result.status == "incomplete"
    assert result.next_snapshot is None
    assert result.observations == []
