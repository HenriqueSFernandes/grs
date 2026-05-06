# Network Chaos Tool

A programmable chaos engineering tool that targets Docker-based network topologies. It injects network faults, like latency, packet loss, and more, into running containers at runtime using `tc` (traffic control) via a privileged sidecar, without requiring any special capabilities inside the target containers themselves.

## Goal

The end goal is a full-featured chaos engineering platform for Docker networks. It will allow users to define fault scenarios (e.g., "break OSPF adjacency," "add 200ms latency + 10% packet loss on an uplink") and run them on demand against containerized infrastructure. An observability stack will monitor and record how the network recovers.

## What Has Been Done So Far (Phase 1)

Phase 1 is a fully functional Proof of Concept (PoC) that proves we can manipulate the Linux kernel network parameters of any Docker container to simulate disasters.

### Architecture

- **One-shot privileged sidecar (`chaos-sidecar`)**: A Docker image containing the injector logic. It runs with `--privileged` and `--pid=host`, mounts the Docker socket, and enters the target container's network namespace using `nsenter` to run `tc` commands directly.
- **Host-side CLI wrapper (`chaosctl`)**: A lightweight Python script that hides the `docker run` boilerplate. It auto-builds the sidecar image if missing and forwards your arguments transparently.
- **Effect stacking**: Latency and packet loss can be combined. Running `--action latency` then `--action loss` produces a single composite `tc` rule (`delay 500ms loss 20%`) instead of overwriting the previous effect.
- **Idempotent recovery**: A `--action clear` command removes all `tc` rules and restores normal network behavior.
- **Zero victim requirements**: Target containers need **no extra capabilities**, no `iproute2`, and no pre-configuration. Any running Docker container can be a target.

### Supported Faults

| Action    | Description                                                |
| --------- | ---------------------------------------------------------- |
| `latency` | Add a fixed delay (ms) to all outgoing traffic.            |
| `loss`    | Add a random packet loss (%) to all outgoing traffic.      |
| `clear`   | Remove all `tc` rules and restore normal network behavior. |

## Prerequisites

- Docker Engine running locally.
- Python 3.10+ with [uv](https://github.com/astral-sh/uv) installed.
- A Linux host (or VM) where `nsenter` and `tc` are available.

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
uv run chaosctl --target victim --action latency --value 500

# Verify the effect
docker exec victim ping -c 4 8.8.8.8

# Stack 20% packet loss on top
uv run chaosctl --target victim --action loss --value 20

# Verify both effects
docker exec victim ping -c 20 8.8.8.8

# Recover
uv run chaosctl --target victim --action clear

# Verify recovery
docker exec victim ping -c 4 8.8.8.8
```

### 4. Force rebuild the sidecar (optional)

If you modify the sidecar `Dockerfile` or the injector code:

```bash
uv run chaosctl --target victim --action clear --rebuild
```

## Project Structure

```
proj/
├── pyproject.toml              # uv project config
├── uv.lock                     # Locked dependency tree
├── Dockerfile                  # Sidecar image definition
├── README.md                   # This file
├── injector/                   # Core chaos logic
│   ├── cli.py                  # Runs inside sidecar (nsenter logic)
│   ├── docker_client.py        # Resolves container name -> PID
│   ├── network_chaos.py        # tc command builder with stacking
│   ├── sidecar_runner.py       # Host wrapper (chaosctl entrypoint)
│   └── __main__.py             # Entry point for `python -m injector`
└── tests/
    └── victim/
        └── Dockerfile          # Minimal Alpine victim for testing
```
