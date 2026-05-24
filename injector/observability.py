"""Helpers for recording chaos events for the observability stack."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_EVENT_LOG_PATH = Path("/observability/data/chaos-events.jsonl")


def get_event_log_path() -> Path | None:
    """Return the configured event log path, if observability is enabled."""
    configured_path = os.getenv("CHAOS_EVENT_LOG_PATH")
    if not configured_path:
        return None
    return Path(configured_path)


def record_event(
    *,
    target: str,
    action: str,
    status: str,
    value: int | None = None,
    message: str | None = None,
) -> None:
    """Append a single chaos event to the shared JSONL event log."""
    event_log_path = get_event_log_path() or DEFAULT_EVENT_LOG_PATH
    event_log_path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, object] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target": target,
        "action": action,
        "status": status,
    }
    if value is not None:
        payload["value"] = value
    if message:
        payload["message"] = message

    with event_log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.write("\n")