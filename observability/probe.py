"""Continuous ping probe for live latency and loss metrics."""

from __future__ import annotations

import argparse
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import docker
from docker.errors import NotFound


PING_OUTPUT_RE = re.compile(
    r"(?P<transmitted>\d+) packets transmitted, (?P<received>\d+) received, (?P<loss>[\d.]+)% packet loss"
)
PING_RTT_RE = re.compile(r"rtt min/avg/max/(?:mdev|stddev) = (?P<min>[\d.]+)/(?P<avg>[\d.]+)/(?P<max>[\d.]+)/(?P<jitter>[\d.]+) ms")


@dataclass
class ProbeState:
    target: str
    target_ip: str | None = None
    rtt_ms: float | None = None
    loss_percent: float | None = None
    failures_total: int = 0
    successes_total: int = 0
    last_check_seconds: float | None = None
    last_error: str | None = None


STATE = ProbeState(target="")
STATE_LOCK = threading.Lock()


def _resolve_target_ip(target_name: str) -> str:
    client = docker.from_env()
    try:
        container = client.containers.get(target_name)
    except NotFound as exc:
        raise RuntimeError(f"Target container '{target_name}' not found.") from exc

    container.reload()
    ip_address = container.attrs.get("NetworkSettings", {}).get("IPAddress")
    if not ip_address:
        networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})
        for network_info in networks.values():
            candidate = network_info.get("IPAddress")
            if candidate:
                ip_address = candidate
                break

    if not ip_address:
        raise RuntimeError(f"Could not determine an IP address for '{target_name}'.")
    return ip_address


def _parse_ping_output(output: str) -> tuple[float, float]:
    loss_match = PING_OUTPUT_RE.search(output)
    if not loss_match:
        raise RuntimeError(f"Could not parse ping summary: {output.strip()}")

    loss_percent = float(loss_match.group("loss"))
    rtt_match = PING_RTT_RE.search(output)
    if not rtt_match:
        raise RuntimeError(f"Could not parse ping RTT summary: {output.strip()}")

    avg_rtt = float(rtt_match.group("avg"))
    return avg_rtt, loss_percent


def _probe_once(target_name: str, packet_count: int, timeout_seconds: int) -> None:
    ip_address = _resolve_target_ip(target_name)
    command = [
        "ping",
        "-n",
        "-q",
        "-c",
        str(packet_count),
        "-W",
        str(timeout_seconds),
        ip_address,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    timestamp = time.time()

    with STATE_LOCK:
        STATE.target = target_name
        STATE.target_ip = ip_address
        STATE.last_check_seconds = timestamp

        if result.returncode != 0 and not result.stdout:
            STATE.failures_total += 1
            STATE.last_error = result.stderr.strip() or "ping command failed"
            STATE.loss_percent = 100.0
            STATE.rtt_ms = None
            return

        try:
            rtt_ms, loss_percent = _parse_ping_output(result.stdout)
            STATE.rtt_ms = rtt_ms
            STATE.loss_percent = loss_percent
            STATE.successes_total += 1
            STATE.last_error = None
            if loss_percent > 0:
                STATE.failures_total += 1
        except RuntimeError as exc:
            STATE.failures_total += 1
            STATE.last_error = str(exc)
            STATE.loss_percent = 100.0
            STATE.rtt_ms = None


def _probe_loop(target_name: str, interval_seconds: int, packet_count: int, timeout_seconds: int) -> None:
    while True:
        try:
            _probe_once(target_name, packet_count, timeout_seconds)
        except Exception as exc:  # pragma: no cover - defensive loop guard
            with STATE_LOCK:
                STATE.target = target_name
                STATE.last_check_seconds = time.time()
                STATE.failures_total += 1
                STATE.last_error = str(exc)
                STATE.loss_percent = 100.0
                STATE.rtt_ms = None
        time.sleep(interval_seconds)


def _metric_line(name: str, value: object, labels: dict[str, object] | None = None) -> str:
    labels = labels or {}
    if labels:
        parts = []
        for key, label_value in labels.items():
            escaped = str(label_value).replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'{key}="{escaped}"')
        label_text = "{" + ",".join(parts) + "}"
    else:
        label_text = ""
    return f"{name}{label_text} {value}"


def render_metrics() -> str:
    with STATE_LOCK:
        state = ProbeState(**STATE.__dict__)

    lines = [
        "# HELP chaos_probe_up Whether the live probe has a current result.",
        "# TYPE chaos_probe_up gauge",
        _metric_line(
            "chaos_probe_up",
            1 if state.rtt_ms is not None else 0,
            {"target": state.target, "target_ip": state.target_ip or "unknown"},
        ),
        "# HELP chaos_probe_rtt_ms Latest average RTT from the live probe.",
        "# TYPE chaos_probe_rtt_ms gauge",
        _metric_line(
            "chaos_probe_rtt_ms",
            state.rtt_ms if state.rtt_ms is not None else 0,
            {"target": state.target, "target_ip": state.target_ip or "unknown"},
        ),
        "# HELP chaos_probe_loss_percent Latest packet loss from the live probe.",
        "# TYPE chaos_probe_loss_percent gauge",
        _metric_line(
            "chaos_probe_loss_percent",
            state.loss_percent if state.loss_percent is not None else 100,
            {"target": state.target, "target_ip": state.target_ip or "unknown"},
        ),
        "# HELP chaos_probe_failures_total Total probe iterations that reported loss or errors.",
        "# TYPE chaos_probe_failures_total counter",
        _metric_line(
            "chaos_probe_failures_total",
            state.failures_total,
            {"target": state.target, "target_ip": state.target_ip or "unknown"},
        ),
        "# HELP chaos_probe_successes_total Total successful probe iterations.",
        "# TYPE chaos_probe_successes_total counter",
        _metric_line(
            "chaos_probe_successes_total",
            state.successes_total,
            {"target": state.target, "target_ip": state.target_ip or "unknown"},
        ),
        "# HELP chaos_probe_last_check_seconds Unix timestamp of the last completed probe.",
        "# TYPE chaos_probe_last_check_seconds gauge",
        _metric_line(
            "chaos_probe_last_check_seconds",
            state.last_check_seconds if state.last_check_seconds is not None else 0,
            {"target": state.target, "target_ip": state.target_ip or "unknown"},
        ),
    ]

    if state.last_error:
        lines.extend(
            [
                "# HELP chaos_probe_last_error_info Non-zero value when the last probe failed.",
                "# TYPE chaos_probe_last_error_info gauge",
                _metric_line(
                    "chaos_probe_last_error_info",
                    1,
                    {"target": state.target, "error": state.last_error[:120]},
                ),
            ]
        )

    lines.append("")
    return "\n".join(lines)


def serve_metrics(host: str, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path not in {"/", "/metrics"}:
                self.send_response(404)
                self.end_headers()
                return

            payload = render_metrics().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):  # noqa: A003
            return

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Serving live probe metrics on http://{host}:{port}/metrics")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a continuous ping probe against a Docker container.")
    parser.add_argument("--target", default="victim")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--interval", type=int, default=2)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=1)
    args = parser.parse_args()

    with STATE_LOCK:
        STATE.target = args.target

    thread = threading.Thread(
        target=_probe_loop,
        args=(args.target, args.interval, args.count, args.timeout),
        daemon=True,
    )
    thread.start()
    serve_metrics(args.host, args.port)


if __name__ == "__main__":
    main()