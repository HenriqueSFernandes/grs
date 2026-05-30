# Agent Instructions — Network Chaos Tool

## Project at a glance
- Python 3.10+ CLI tool that injects network faults (latency, packet loss) into Docker containers via `tc` (traffic control), using a privileged sidecar.
- Real code lives in `injector/`. `main.py` at the root is a dead stub—safe to remove.
- Build system: **hatchling**. Package manager: **uv**.

## Entry points
- **`chaosctl`** (`injector.sidecar_runner:main`) — Host-side wrapper. Spins up the privileged sidecar container to run `tc` against a target container.
- **`chaos`** (`injector.cli:main`) — Runs *inside* the sidecar. Invoked by `chaosctl`; do not call directly from the host.
- `python -m injector` is wired to `injector.cli:main`.

## Development setup
```bash
# Environment is managed via Nix flake (see .envrc)
uv pip install -e .
```

## Running / verifying changes
There are **no automated Python tests**. Verification is manual against a victim container:
```bash
# Build and run the victim
docker build -t chaos-victim tests/victim
docker run -d --name victim chaos-victim

# Test chaosctl
chaosctl --target victim --action latency --value 500
chaosctl --target victim --action loss --value 20
chaosctl --target victim --action clear
```

## Lint / format
No config file exists—use default settings:
```bash
ruff check .
ruff format .
```

## Build and release
```bash
# Build wheel
uv build

# Bump version, commit, and tag (syncs pyproject.toml + injector/__init__.py)
./bump-version.sh

# Push triggers CI on v*.*.* tags
git push && git push --tags
```

## Key architecture notes
- The `Dockerfile` at the repo root defines the **sidecar image**, not the application.
- `pyproject.toml` uses `force-include` to bundle `Dockerfile`, `pyproject.toml`, and `README.md` into the wheel. This lets `chaosctl` build the sidecar locally when the registry is unreachable.
- Sidecar image resolution order (`chaosctl`):
  1. Check local Docker cache for `rickysf/chaos-sidecar:<version>`.
  2. Pull from Docker Hub (if not `--local-build`).
  3. Fallback to building from the bundled source.
- `injector/network_chaos.py` uses `nsenter -t <pid> -n tc ...` to manipulate the target container's network namespace. Requires a **Linux host** (or VM) where `nsenter` and `tc` are available.

## CI / publish
- `.github/workflows/publish.yml` triggers on `v*.*.*` tags.
- Order matters: Docker image is built and pushed first; PyPI publish depends on it.

## Agent skills

### Issue tracker

Issues live as GitHub issues in this repo. Use the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default mattpocock/skills vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context repo — one `CONTEXT.md` + `docs/adr/` at the repo root (create lazily if absent). See `docs/agents/domain.md`.
