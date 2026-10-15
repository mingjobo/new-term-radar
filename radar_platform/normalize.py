from __future__ import annotations

import re
import unicodedata

from .models import EvidenceInput


_SPACE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Normalize presentation differences without deleting meaningful symbols."""
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", value).casefold()).strip()


def _resolve_alias(value: str, aliases: dict[str, str]) -> str:
    current = value
    visited: set[str] = set()
    while current in aliases:
        if current in visited:
            raise ValueError(f"alias cycle includes {current!r}")
        visited.add(current)
        current = aliases[current]
    return current


def canonical_key(event: EvidenceInput, aliases: dict[str, str]) -> str:
    if event.kind == "generic":
        return f"generic:{normalize_text(event.language)}:{normalize_text(event.name)}"

    identity = normalize_text(f"{event.source_instance}:{event.entity_key}")
    normalized_aliases = {normalize_text(key): normalize_text(value) for key, value in aliases.items()}
    identity = _resolve_alias(identity, normalized_aliases)
    return f"{event.kind}:{identity}"

