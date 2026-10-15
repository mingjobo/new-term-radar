from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from radar_platform.adapters import huggingface
from radar_platform.models import HttpResponse, PlatformConfig, SourceSnapshot


NOW = datetime(2026, 10, 15, 8, 17, tzinfo=timezone.utc)


class JsonHttp:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def request(self, method: str, url: str, *, headers=None, body=None) -> HttpResponse:
        self.urls.append(url)
        return HttpResponse(200, {"content-type": "application/json"}, json.dumps(self.payload).encode())


@pytest.fixture
def cfg() -> PlatformConfig:
    return PlatformConfig(
        sources={"hf:models": {"enabled": True}, "hf:spaces": {"enabled": True}},
        roots=[],
        aliases={},
        hf_task_map={},
        budgets={},
        timezone="Asia/Shanghai",
    )


def _model(model_id: str, *, likes: int = 1, task: str = "text-generation") -> dict:
    return {"id": model_id, "likes": likes, "pipeline_tag": task, "trendingScore": likes * 2}


def test_first_fetch_only_builds_top_100_baseline(cfg: PlatformConfig) -> None:
    items = [_model(f"org/model-{index}") for index in range(100)]
    result = huggingface.collect(
        cfg,
        SourceSnapshot(0, {}, None),
        NOW,
        JsonHttp(items),
        source_instance="hf:models",
    )

    assert result.status == "baseline"
    assert result.observations == []
    assert result.next_snapshot["ids"] == [item["id"] for item in items]
    assert result.coverage == {"complete": True, "items": 100, "top": 100}


def test_only_a_new_entry_inside_top_50_is_a_discovery(cfg: PlatformConfig) -> None:
    old_ids = [f"org/old-{index}" for index in range(100)]
    previous = SourceSnapshot(1, {"ids": old_ids, "slot": "previous"}, NOW)
    outside = [_model(item) for item in old_ids[:50]] + [_model("org/rank-51-new")]

    outside_result = huggingface.collect(cfg, previous, NOW, JsonHttp(outside), source_instance="hf:models")
    assert [event for event in outside_result.observations if event.is_discovery] == []

    inside = [_model("org/Qwen-Image-2.1-GGUF", likes=500)] + [_model(item) for item in old_ids[:50]]
    result = huggingface.collect(cfg, previous, NOW, JsonHttp(inside), source_instance="hf:models")
    discoveries = [event for event in result.observations if event.is_discovery]

    assert result.status == "ok"
    assert len(discoveries) == 1
    assert discoveries[0].external_id == "org/Qwen-Image-2.1-GGUF"
    assert discoveries[0].name == "qwen image 2.1"
    assert discoveries[0].metrics["rank"] == 1
    assert discoveries[0].url == "https://huggingface.co/org/Qwen-Image-2.1-GGUF"


def test_same_slot_rerun_does_not_discover_again(cfg: PlatformConfig) -> None:
    previous = SourceSnapshot(1, {"ids": ["org/old"]}, NOW)
    items = [_model("org/new"), _model("org/old")]
    first = huggingface.collect(cfg, previous, NOW, JsonHttp(items), source_instance="hf:models")
    advanced = SourceSnapshot(2, first.next_snapshot, NOW)

    repeated = huggingface.collect(cfg, advanced, NOW, JsonHttp(items), source_instance="hf:models")

    assert [event for event in repeated.observations if event.is_discovery] == []
    assert repeated.next_snapshot == first.next_snapshot


@pytest.mark.parametrize("payload", [[], {}, [{"likes": 3}], [{"id": 42}]])
def test_empty_or_changed_shape_does_not_replace_baseline(cfg: PlatformConfig, payload) -> None:
    previous = SourceSnapshot(4, {"ids": ["org/keep-me"], "slot": "old"}, NOW)

    result = huggingface.collect(cfg, previous, NOW, JsonHttp(payload), source_instance="hf:models")

    assert result.status == "incomplete"
    assert result.next_snapshot is None
    assert result.observations == []


def test_quantized_model_and_demo_merge_only_with_explicit_alias(cfg: PlatformConfig) -> None:
    model_previous = SourceSnapshot(1, {"ids": ["org/old"]}, NOW)
    space_previous = SourceSnapshot(1, {"ids": ["org/old-space"]}, NOW)
    model_id = "org/Foo-2.1-GGUF"
    space_id = "org/Foo-2.1-Demo"

    model = huggingface.collect(
        cfg, model_previous, NOW, JsonHttp([_model(model_id)]), source_instance="hf:models"
    ).observations[0]
    space = huggingface.collect(
        cfg,
        space_previous,
        NOW,
        JsonHttp([{"id": space_id, "likes": 4, "sdk": "gradio", "trendingScore": 8}]),
        source_instance="hf:spaces",
    ).observations[0]
    assert model.entity_key != space.entity_key

    aliased = replace(cfg, aliases={f"hf:spaces:{space_id}": f"hf:models:{model_id}"})
    aliased_space = huggingface.collect(
        aliased,
        space_previous,
        NOW,
        JsonHttp([{"id": space_id, "likes": 4, "sdk": "gradio", "trendingScore": 8}]),
        source_instance="hf:spaces",
    ).observations[0]
    assert model.entity_key == aliased_space.entity_key
