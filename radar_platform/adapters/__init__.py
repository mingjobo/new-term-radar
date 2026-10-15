from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from radar_platform.models import HttpResponse


class AdapterError(RuntimeError):
    pass


def slot_for(now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("collection time must include a timezone")
    utc = now.astimezone(timezone.utc)
    hour = (utc.hour // 8) * 8
    return utc.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")


def json_body(response: HttpResponse, *, source: str) -> Any:
    if response.status != 200:
        raise AdapterError(f"{source} returned HTTP {response.status}")
    try:
        return json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterError(f"{source} returned invalid JSON") from exc

