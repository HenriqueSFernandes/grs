"""Prometheus exporter for chaos events recorded by the sidecar."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable


DEFAULT_LOG_PATH = Path("/observability/data/chaos-events.jsonl")


@dataclass(frozen=True)
class Event:
    timestamp: datetime
    target: str
    action: str
    status: str
    value: int | None = None
    message: str | None = None


def _parse_event(line: str) -> Event | None:
    try:
        payload = json.loads(line)
        return Event(
            timestamp=datetime.fromisoformat(payload["timestamp"]),
            target=str(payload["target"]),
            action=str(payload["action"]),
            status=str(payload["status"]),
            value=payload.get("value"),
            message=payload.get("message"),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _load_events(log_path: Path) -> list[Event]:
    if not log_path.exists():
        return []

    events: list[Event] = []
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            event = _parse_event(line)
            if event is not None:
                events.append(event)
    return events


def _format_labels(labels: dict[str, object]) -> str:
    if not labels:
        return ""
    parts = []
    for key, value in labels.items():
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'{key}="{escaped}"')
    return "{" + ",".join(parts) + "}"


def _metric_line(name: str, value: object, labels: dict[str, object] | None = None) -> str:
    label_text = _format_labels(labels or {})
    return f"{name}{label_text} {value}"


def render_metrics(events: Iterable[Event]) -> str:
    events = list(events)
    action_totals: Counter[tuple[str, str]] = Counter()
    active_faults: dict[str, dict[str, int]] = defaultdict(dict)
    last_event: Event | None = None

    for event in events:
        action_totals[(event.action, event.status)] += 1
        last_event = event
        if event.status != "success":
            continue

        if event.action == "clear":
            active_faults[event.target].clear()
            continue

        if event.action in {"latency", "loss"} and event.value is not None:
            active_faults[event.target][event.action] = int(event.value)

    seen_targets = sorted(active_faults)
    active_targets = sum(1 for target in seen_targets if active_faults[target])
    active_fault_count = sum(len(state) for state in active_faults.values())

    lines = [
        "# HELP chaos_actions_total Total chaos actions executed by outcome.",
        "# TYPE chaos_actions_total counter",
    ]
    for (action, status), count in sorted(action_totals.items()):
        lines.append(
            _metric_line(
                "chaos_actions_total",
                count,
                {"action": action, "status": status},
            )
        )

    lines.extend(
        [
            "# HELP chaos_active_targets Number of targets with at least one active fault.",
            "# TYPE chaos_active_targets gauge",
            _metric_line("chaos_active_targets", active_targets),
            "# HELP chaos_active_faults Number of currently active fault types.",
            "# TYPE chaos_active_faults gauge",
            _metric_line("chaos_active_faults", active_fault_count),
            "# HELP chaos_target_fault_active Whether a target currently has an active fault of a given type.",
            "# TYPE chaos_target_fault_active gauge",
        ]
    )

    for target in seen_targets:
        state = active_faults[target]
        for fault in ("latency", "loss"):
            lines.append(
                _metric_line(
                    "chaos_target_fault_active",
                    1 if fault in state else 0,
                    {"target": target, "fault": fault},
                )
            )

    lines.extend(
        [
            "# HELP chaos_target_fault_value Current fault value for a target and fault type.",
            "# TYPE chaos_target_fault_value gauge",
        ]
    )

    for target in seen_targets:
        state = active_faults[target]
        lines.append(
            _metric_line(
                "chaos_target_fault_value",
                state.get("latency", 0),
                {"target": target, "fault": "latency", "unit": "ms"},
            )
        )
        lines.append(
            _metric_line(
                "chaos_target_fault_value",
                state.get("loss", 0),
                {"target": target, "fault": "loss", "unit": "percent"},
            )
        )

    if last_event is not None:
        lines.extend(
            [
                "# HELP chaos_last_event_timestamp_seconds Unix timestamp of the last observed chaos event.",
                "# TYPE chaos_last_event_timestamp_seconds gauge",
                _metric_line(
                    "chaos_last_event_timestamp_seconds",
                    last_event.timestamp.timestamp(),
                ),
                "# HELP chaos_last_event_info Labels describing the most recent chaos event.",
                "# TYPE chaos_last_event_info gauge",
                _metric_line(
                    "chaos_last_event_info",
                    1,
                    {
                        "target": last_event.target,
                        "action": last_event.action,
                        "status": last_event.status,
                        "value": last_event.value if last_event.value is not None else "",
                    },
                ),
            ]
        )

    lines.append("")
    return "\n".join(lines)


def serve_metrics(log_path: Path, host: str, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path not in {"/", "/metrics"}:
                self.send_response(404)
                self.end_headers()
                return

            payload = render_metrics(_load_events(log_path)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):  # noqa: A003
            return

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Serving Prometheus metrics on http://{host}:{port}/metrics")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve chaos metrics for Prometheus.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    args = parser.parse_args()

    serve_metrics(args.log_path, args.host, args.port)


if __name__ == "__main__":
    main()