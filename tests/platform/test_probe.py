from __future__ import annotations

from datetime import datetime, timezone

from radar.platform.models import CollectionResult, EvidenceInput
from scripts.platform_probe import expand_sources, summarize


def test_probe_aliases_expand_to_three_free_source_instances() -> None:
    assert expand_sources("github,hf") == ["github:breakout", "hf:models", "hf:spaces"]
    assert expand_sources("hf:spaces,github:breakout") == ["hf:spaces", "github:breakout"]


def test_probe_summary_reports_structure_without_dumping_snapshot() -> None:
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    event = EvidenceInput(
        source_instance="github:breakout",
        external_id="1",
        entity_key="name:github:breakout:1",
        name="radar",
        kind="name",
        language="en",
        url="https://github.com/acme/radar",
        excerpt="description",
        observed_at=now,
        data_window={"slot": "slot"},
        metrics={"stars": 1000},
        content_hash="hash",
        is_discovery=True,
    )
    result = CollectionResult("ok", [event], {"large": ["raw", "state"]}, {"complete": True})

    assert summarize(result) == {
        "status": "ok",
        "observations": 1,
        "discoveries": 1,
        "coverage": {"complete": True},
        "snapshot_ready": True,
    }
