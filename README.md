# Network Chaos Tool

A programmable chaos engineering tool that targets Docker-based network topologies. It injects network faults - latency, packet loss, and more - into running containers at runtime using `tc` (traffic control) via a privileged sidecar, without requiring any special capabilities inside t0he target containers themselves.

## Goal

The goal is a full-featured0 chaos engineering platform for Docker networks. It allows users to define fault scenarios and run them on demand against containerized infrastructure, with live observability for how the network responds.

## Features

- **Privileged sidecar (`chaos-sidecar`)**: Enters the target container's network namespace using `nsenter` to run `tc` commands directly.
- **Composite faults**: Latency and packet loss can be combined into a single `tc` rule.
- **Auto-clear**: Optional duration-based cleanup via `--duration`.
- **Scenario runner**: Run YAML-defined scenarios with `chaosctl run`.
- **Live dashboard**: Web UI with live tc metrics and ping measurements via `chaosctl serve`.
- **Zero victim requirements**: Target containers need **no extra capabilities**, no `iproute2`, and no pre-configuration.
- **Sidecar image resolution**: Uses local cache, then Docker Hub, then bundled `Dockerfile` fallback.

### Supported Faults

| Action | Description |
|--------|-------------|
| `latency` | Add a fixed delay (ms) to all outgoing traffic. |
| `loss` | Add a random packet loss (%) to all outgoing traffic. |
| `clear` | Remove all `tc` rules and restore normal network behavior. |
0
## Prerequisites

- Docker Engine running locally.
- Python 3.10+.
- A Linux host (or VM) where `nsenter` and `tc` are available.

## Installation

```bash
pip install network-chaos-tool
```

For development, you can also install from source with [uv](https://github.com/astral-sh/uv):

```bash
uv pip install -e .
```

## Quick Start

### 1. Build a victim container

```bash
docker build -t chaos-victim tests/victim
docker run -d --name victim chaos-victim
```

### 2. Inject chaos via `chaosctl`

```bash
# Add 500ms latency
chaosctl --target victim --action latency --value 500

# Stack 20% packet loss on top (composite mode)
chaosctl --target victim --latency 500 --loss 20

# Auto-clear after 5 seconds
chaosctl --target victim --action loss --value 20 --duration 5000

# Recover
chaosctl --target victim --action clear
```

### 3. Start the live dashboard

```bash
chaosctl serve --port 8080
```

Open `http://localhost:8080`. The server auto-starts a `chaos-monitor` sidecar for live metrics.

### 4. Run a scenario YAML

```bash
chaosctl run examples/full-test.yaml

# Validate only
chaosctl run examples/full-test.yaml --dry-run
```

### 5. Advanced options

```bash
# Use a specific sidecar image version
chaosctl --target victim --action clear --sidecar-version 0.2.0

# Force a local build from bundled source (offline mode)
chaosctl --target victim --action clear --local-build

# Manually start a persistent monitor sidecar
chaosctl monitor --monitor-host-port 9090
```

## CLI Reference

### chaosctl (host-side wrapper)

```bash
# Inject faults
chaosctl --target <container> --action latency --value <ms>
chaosctl --target <container> --action loss --value <percent>
chaosctl --target <container> --action clear

# Composite faults
chaosctl --target <container> --latency <ms> --loss <percent>

# Auto-clear after N ms
chaosctl --target <container> --action loss --value 20 --duration 5000

# Serve dashboard
chaosctl serve --host 0.0.0.0 --port 8080

# Run scenario YAML
chaosctl run path/to/scenario.yaml --dry-run

# Start monitor sidecar (optional; dashboard auto-starts it)
chaosctl monitor --monitor-host-port 9090
```

### chaos (sidecar-only)

`chaos` runs inside the privileged sidecar container and is not meant to be invoked directly on the host.

## Project Structure

```
proj/
├── pyproject.toml              # Project config (hatchling)
├── uv.lock                     # Locked dependency tree
├── Dockerfile                  # Sidecar image definition
├── LICENSE                     # MIT License
├── README.md                   # This file
├── injector/                   # Core chaos logic
│   ├── __init__.py             # Package metadata
│   ├── __main__.py             # Entry point for `python -m injector`
│   ├── cli.py                  # Runs inside sidecar (nsenter + monitor)
│   ├── docker_client.py        # Resolves container name -> PID
│   ├── monitor.py              # Monitor FastAPI app (metrics + ping)
│   ├── network_chaos.py         # tc command builder with stacking
│   ├── scenario_executor.py    # YAML scenario runner
│   ├── sidecar_runner.py       # Host wrapper (chaosctl entrypoint)
│   ├── templates/              # Dashboard HTML templates
│   └── web_server.py           # Dashboard FastAPI app
├── examples/                   # Scenario YAML examples
└── tests/
    └── victim/
        └── Dockerfile          # Minimal Alpine victim for testing
```

## Roadmap

- Support for additional fault types: jitter, corruption, bandwidth throttling, network partitions.
- Export metrics to external observability stacks (Prometheus/Grafana).
