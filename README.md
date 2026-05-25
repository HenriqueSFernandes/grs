# Network Chaos Tool

A programmable chaos engineering tool that targets Docker-based network topologies. It injects network faults — latency, packet loss, and more — into running containers at runtime using `tc` (traffic control) via a privileged sidecar, without requiring any special capabilities inside the target containers themselves.

## Goal

The end goal is a full-featured chaos engineering platform for Docker networks. It will allow users to define fault scenarios (e.g., "break OSPF adjacency," "add 200ms latency + 10% packet loss on an uplink") and run them on demand against containerized infrastructure. An observability stack will monitor and record how the network recovers.

## What Has Been Done So Far

### Phase 1: Core PoC

A fully functional Proof of Concept that proves we can manipulate the Linux kernel network parameters of any Docker container to simulate disasters.

- **One-shot privileged sidecar (`chaos-sidecar`)**: Enters the target container's network namespace using `nsenter` to run `tc` commands directly.
- **Effect stacking**: Latency and packet loss can be combined into a single composite `tc` rule.
- **Idempotent recovery**: `--action clear` removes all `tc` rules and restores normal network behavior.
- **Zero victim requirements**: Target containers need **no extra capabilities**, no `iproute2`, and no pre-configuration.

### Phase 2: Distribution

The tool is now **pip-installable** and published to PyPI. The sidecar image is resolved automatically:

1. Check local Docker cache for the pinned version.
2. If missing, try pulling `rickysf/chaos-sidecar:<version>` from Docker Hub.
3. If the registry is unreachable, fall back to building the sidecar from the bundled `Dockerfile`.

### Supported Faults

| Action | Description |
|--------|-------------|
| `latency` | Add a fixed delay (ms) to all outgoing traffic. |
| `loss` | Add a random packet loss (%) to all outgoing traffic. |
| `clear` | Remove all `tc` rules and restore normal network behavior. |

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

### 1. Build the victim test container

```bash
docker build -t chaos-victim tests/victim
docker run -d --name victim chaos-victim
```

### 2. Verify baseline connectivity

```bash
docker exec victim ping -c 4 8.8.8.8
```

### 3. Inject chaos via `chaosctl`

```bash
# Add 500ms latency
chaosctl --target victim --action latency --value 500

# Verify the effect
docker exec victim ping -c 4 8.8.8.8

# Stack 20% packet loss on top
chaosctl --target victim --action loss --value 20

# Verify both effects
docker exec victim ping -c 20 8.8.8.8

# Recover
chaosctl --target victim --action clear

# Verify recovery
docker exec victim ping -c 4 8.8.8.8
```

### 4. Advanced options

```bash
# Use a specific sidecar image version
chaosctl --target victim --action clear --sidecar-version 0.2.0

# Force a local build from bundled source (offline mode)
chaosctl --target victim --action clear --local-build
```

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
│   ├── cli.py                  # Runs inside sidecar (nsenter logic)
│   ├── docker_client.py        # Resolves container name -> PID
│   ├── network_chaos.py        # tc command builder with stacking
│   └── sidecar_runner.py       # Host wrapper (chaosctl entrypoint)
└── tests/
    └── victim/
        └── Dockerfile          # Minimal Alpine victim for testing
```

## Next Steps (Phase 3)

- Scenario definitions via YAML config files.
- Timed chaos (auto-clear after N seconds).
- Support for additional fault types: jitter, corruption, bandwidth throttling, network partitions.
- Observability hooks (Prometheus metrics, Grafana dashboard).
