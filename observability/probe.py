"""Continuous ping probe for live latency and loss metrics."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import fmean

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


STATE_BY_TARGET: dict[str, ProbeState] = {}
STATE_LOCK = threading.Lock()
LOSS_HISTORY_SIZE = 20
LOSS_HISTORY_BY_TARGET: dict[str, deque[float]] = {}


def _ensure_target_state(target_name: str) -> ProbeState:
    state = STATE_BY_TARGET.get(target_name)
    if state is None:
        state = ProbeState(target=target_name)
        STATE_BY_TARGET[target_name] = state
    LOSS_HISTORY_BY_TARGET.setdefault(target_name, deque(maxlen=LOSS_HISTORY_SIZE))
    return state


def _parse_targets_text(targets_text: str) -> list[str]:
    if not targets_text.strip():
        return []
    return [target.strip() for target in targets_text.split(",") if target.strip()]


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
        state = _ensure_target_state(target_name)
        loss_history = LOSS_HISTORY_BY_TARGET[target_name]
        state.target_ip = ip_address
        state.last_check_seconds = timestamp

        if result.returncode != 0 and not result.stdout:
            state.failures_total += 1
            state.last_error = result.stderr.strip() or "ping command failed"
            state.loss_percent = 100.0
            state.rtt_ms = None
            loss_history.append(100.0)
            return

        try:
            rtt_ms, loss_percent = _parse_ping_output(result.stdout)
            state.rtt_ms = rtt_ms
            state.loss_percent = loss_percent
            loss_history.append(loss_percent)
            state.successes_total += 1
            state.last_error = None
            if loss_percent > 0:
                state.failures_total += 1
        except RuntimeError as exc:
            state.failures_total += 1
            state.last_error = str(exc)
            state.loss_percent = 100.0
            state.rtt_ms = None
            loss_history.append(100.0)


def _probe_loop(
    target_name: str,
    interval_seconds: int,
    packet_count: int,
    timeout_seconds: int,
) -> None:
    while True:
        try:
            _probe_once(target_name, packet_count, timeout_seconds)
        except Exception as exc:  # pragma: no cover - defensive loop guard
            with STATE_LOCK:
                state = _ensure_target_state(target_name)
                state.last_check_seconds = time.time()
                state.failures_total += 1
                state.last_error = str(exc)
                state.loss_percent = 100.0
                state.rtt_ms = None
                LOSS_HISTORY_BY_TARGET[target_name].append(100.0)
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
        states = [ProbeState(**state.__dict__) for state in STATE_BY_TARGET.values()]
        loss_history_by_target = {target: list(samples) for target, samples in LOSS_HISTORY_BY_TARGET.items()}

    lines = [
        "# HELP chaos_probe_up Whether the live probe has a current result.",
        "# TYPE chaos_probe_up gauge",
    ]

    lines.extend(
        [
            "# HELP chaos_probe_rtt_ms Latest average RTT from the live probe.",
            "# TYPE chaos_probe_rtt_ms gauge",
            "# HELP chaos_probe_loss_percent Latest packet loss from the live probe.",
            "# TYPE chaos_probe_loss_percent gauge",
            "# HELP chaos_probe_loss_percent_avg Rolling average packet loss from the live probe.",
            "# TYPE chaos_probe_loss_percent_avg gauge",
            "# HELP chaos_probe_failures_total Total probe iterations that reported loss or errors.",
            "# TYPE chaos_probe_failures_total counter",
            "# HELP chaos_probe_successes_total Total successful probe iterations.",
            "# TYPE chaos_probe_successes_total counter",
            "# HELP chaos_probe_last_check_seconds Unix timestamp of the last completed probe.",
            "# TYPE chaos_probe_last_check_seconds gauge",
        ]
    )

    for state in sorted(states, key=lambda item: item.target):
        loss_samples = loss_history_by_target.get(state.target, [])
        loss_average = fmean(loss_samples) if loss_samples else 0.0
        labels = {"target": state.target, "target_ip": state.target_ip or "unknown"}

        lines.extend(
            [
                _metric_line("chaos_probe_up", 1 if state.rtt_ms is not None else 0, labels),
                _metric_line(
                    "chaos_probe_rtt_ms",
                    state.rtt_ms if state.rtt_ms is not None else 0,
                    labels,
                ),
                _metric_line(
                    "chaos_probe_loss_percent",
                    state.loss_percent if state.loss_percent is not None else 100,
                    labels,
                ),
                _metric_line("chaos_probe_loss_percent_avg", loss_average, labels),
                _metric_line("chaos_probe_failures_total", state.failures_total, labels),
                _metric_line("chaos_probe_successes_total", state.successes_total, labels),
                _metric_line(
                    "chaos_probe_last_check_seconds",
                    state.last_check_seconds if state.last_check_seconds is not None else 0,
                    labels,
                ),
            ]
        )

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
    parser.add_argument(
        "--target",
        action="append",
        dest="target_list",
        help="Name or ID of a target container. Repeat to probe multiple containers.",
    )
    parser.add_argument(
        "--targets",
        help="Comma-separated list of target containers to probe.",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--interval", type=int, default=2)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=1)
    args = parser.parse_args()

    targets: list[str] = []
    if args.targets:
        targets.extend(target.strip() for target in args.targets.split(",") if target.strip())
    if args.target_list:
        targets.extend(args.target_list)
    if not targets:
        env_targets = os.environ.get("PROBE_TARGETS", "")
        if env_targets:
            targets.extend(target.strip() for target in env_targets.split(",") if target.strip())
    if not targets:
        targets = ["victim"]

    unique_targets = list(dict.fromkeys(targets))

    with STATE_LOCK:
        for target_name in unique_targets:
            _ensure_target_state(target_name)

    for target_name in unique_targets:
        thread = threading.Thread(
            target=_probe_loop,
            args=(target_name, args.interval, args.count, args.timeout),
            daemon=True,
        )
        thread.start()

    serve_metrics(args.host, args.port)


if __name__ == "__main__":
    main()