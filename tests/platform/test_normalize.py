from __future__ import annotations

from radar.platform.models import EvidenceInput
from radar.platform.normalize import canonical_key, normalize_text


def _event(*, entity_key: str, name: str, observed_at) -> EvidenceInput:
    return EvidenceInput(
        source_instance="github:breakout",
        external_id=entity_key,
        entity_key=entity_key,
        name=name,
        kind="name",
        language="en",
        url=f"https://github.com/{entity_key}",
        excerpt="",
        observed_at=observed_at,
        data_window={},
        metrics={},
        content_hash="hash",
        is_discovery=True,
    )


def test_normalize_preserves_meaningful_symbols_and_versions() -> None:
    assert normalize_text("  C++  ") == "c++"
    assert normalize_text("C#") == "c#"
    assert normalize_text("Model  2.1") == "model 2.1"
    assert normalize_text("Model 2.2") == "model 2.2"
    assert normalize_text("C++") != normalize_text("C#")
    assert normalize_text("model 2.1") != normalize_text("model 2.2")


def test_same_name_different_repositories_remain_distinct(observed_at) -> None:
    first = _event(entity_key="owner-one/radar", name="Radar", observed_at=observed_at)
    second = _event(entity_key="owner-two/radar", name="Radar", observed_at=observed_at)

    assert canonical_key(first, {}) != canonical_key(second, {})


def test_only_explicit_aliases_merge_entities(observed_at) -> None:
    github = _event(entity_key="acme/radar", name="Radar", observed_at=observed_at)
    hf = _event(entity_key="acme-ai/radar", name="Radar", observed_at=observed_at)
    hf = EvidenceInput(**{**hf.__dict__, "source_instance": "hf:models", "url": "https://huggingface.co/acme-ai/radar"})

    assert canonical_key(github, {}) != canonical_key(hf, {})
    aliases = {"hf:models:acme-ai/radar": "github:breakout:acme/radar"}
    assert canonical_key(github, aliases) == canonical_key(hf, aliases)
