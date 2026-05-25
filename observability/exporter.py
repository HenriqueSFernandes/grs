"""Prometheus exporter for chaos events recorded by the sidecar."""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


DEFAULT_LOG_PATH = Path("/observability/data/chaos-events.jsonl")
DEFAULT_PROMETHEUS_BASE_URL = "http://prometheus:9090"
PROMETHEUS_RESET_SELECTORS = (
    '{job="chaos-exporter"}',
    '{job="chaos-probe"}',
)


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


def _truncate_log(log_path: Path) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("", encoding="utf-8")


def _call_prometheus_admin_api(base_url: str, path: str, data: dict[str, str] | None = None) -> None:
        payload = None if data is None else urlencode(data).encode("utf-8")
        request = Request(
                f"{base_url.rstrip('/')}{path}",
                data=payload,
                method="POST",
        )
        with urlopen(request, timeout=10) as response:
                response.read()


def _reset_prometheus_data(base_url: str) -> None:
        for selector in PROMETHEUS_RESET_SELECTORS:
                _call_prometheus_admin_api(
                        base_url,
                        "/api/v1/admin/tsdb/delete_series",
                        {"match[]": selector},
                )
        _call_prometheus_admin_api(base_url, "/api/v1/admin/tsdb/clean_tombstones")


def reset_observability_state(log_path: Path, prometheus_base_url: str) -> None:
        _truncate_log(log_path)
        _reset_prometheus_data(prometheus_base_url)


def _render_reset_page(status: str | None = None, error: str | None = None) -> str:
        message = ""
        if status == "success":
                message = "<p class='success'>Observability data has been cleared.</p>"
        elif error:
                message = f"<p class='error'>{html.escape(error)}</p>"

        return f"""<!doctype html>
<html lang=\"en\">
    <head>
        <meta charset=\"utf-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
        <title>Reset observability data</title>
        <style>
            body {{
                font-family: sans-serif;
                max-width: 42rem;
                margin: 3rem auto;
                padding: 0 1.5rem;
                line-height: 1.5;
            }}
            form {{ margin-top: 1.5rem; }}
            button {{
                background: #c62828;
                border: 0;
                color: white;
                border-radius: 0.5rem;
                padding: 0.85rem 1.2rem;
                font-size: 1rem;
                font-weight: 600;
                cursor: pointer;
            }}
            .success {{ color: #1b5e20; }}
            .error {{ color: #b71c1c; }}
            .note {{ color: #555; }}
        </style>
    </head>
    <body>
        <h1>Reset observability data</h1>
        <p class=\"note\">This clears the JSONL event log and deletes the Prometheus series for the chaos exporter and probe so the dashboard starts fresh.</p>
        {message}
        <form method=\"post\" action=\"/reset\">
            <button type=\"submit\">Clear data now</button>
        </form>
        <p><a href=\"/metrics\">View metrics</a></p>
    </body>
</html>"""


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
            parsed_path = urlparse(self.path)
            if parsed_path.path == "/reset":
                query = parse_qs(parsed_path.query)
                payload = _render_reset_page(
                    status=query.get("status", [None])[0],
                    error=query.get("error", [None])[0],
                ).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            if parsed_path.path not in {"/", "/metrics"}:
                self.send_response(404)
                self.end_headers()
                return

            payload = render_metrics(_load_events(log_path)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):  # noqa: N802
            parsed_path = urlparse(self.path)
            if parsed_path.path != "/reset":
                self.send_response(404)
                self.end_headers()
                return

            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length:
                self.rfile.read(content_length)

            try:
                reset_observability_state(log_path, DEFAULT_PROMETHEUS_BASE_URL)
            except Exception as exc:  # pragma: no cover - reported via the HTML response
                payload = _render_reset_page(error=str(exc)).encode("utf-8")
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/reset?status=success")
            self.end_headers()

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