from __future__ import annotations

from datetime import datetime, timezone

import pytest


@pytest.fixture
def observed_at() -> datetime:
    return datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc)
