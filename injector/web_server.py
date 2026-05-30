"""FastAPI web server for chaos dashboard and API."""

import json
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import docker
import injector
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="Network Chaos Dashboard", version=injector.__version__)

_templates_dir = Path(__file__).parent / "templates"

_docker_client = docker.from_env()

SIDECAR_IMAGE = "rickysf/chaos-sidecar"
SIDECAR_VERSION = injector.__version__

_sidecar_tag: str | None = None


def _ensure_sidecar_image() -> str:
    global _sidecar_tag
    if _sidecar_tag:
        return _sidecar_tag
    tag = f"{SIDECAR_IMAGE}:{SIDECAR_VERSION}"
    result = subprocess.run(
        ["docker", "images", "-q", tag],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("Docker is not available.")
    if not result.stdout.strip():
        subprocess.run(["docker", "pull", tag], check=False)
    _sidecar_tag = tag
    return tag


def _query_tc_metrics(name: str) -> dict:
    try:
        tag = _ensure_sidecar_image()
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--privileged",
                "--pid=host",
                "-v",
                "/var/run/docker.sock:/var/run/docker.sock",
                tag,
                "--target",
                name,
                "--action",
                "status",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return {"latency_ms": None, "loss_pct": None}
        data = json.loads(result.stdout.strip())
        return {
            "latency_ms": data.get("latency_ms"),
            "loss_pct": data.get("loss_pct"),
        }
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        return {"latency_ms": None, "loss_pct": None}


def _get_tc_metrics_batch(names: list[str]) -> dict[str, dict]:
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_query_tc_metrics, name): name for name in names}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception:
                results[name] = {"latency_ms": None, "loss_pct": None}
    return results


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html_path = _templates_dir / "dashboard.html"
    return HTMLResponse(content=html_path.read_text())


@app.get("/api/containers")
async def list_containers():
    containers = _docker_client.containers.list(all=True)
    running_names = [c.name for c in containers if c.status == "running"]
    tc_batch = _get_tc_metrics_batch(running_names) if running_names else {}
    result = []
    for c in containers:
        status = c.status
        tc_metrics = tc_batch.get(c.name, {"latency_ms": None, "loss_pct": None})
        result.append(
            {
                "name": c.name,
                "id": c.short_id,
                "image": c.image.tags[0] if c.image.tags else "unknown",
                "status": status,
                "latency_ms": tc_metrics.get("latency_ms"),
                "loss_pct": tc_metrics.get("loss_pct"),
            }
        )
    return result


@app.get("/api/containers/{name}")
async def get_container(name: str):
    try:
        c = _docker_client.containers.get(name)
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"Container '{name}' not found.")

    status = c.status
    tc_metrics = {"latency_ms": None, "loss_pct": None}
    if status == "running":
        tc_metrics = _query_tc_metrics(c.name)

    return {
        "name": c.name,
        "id": c.short_id,
        "image": c.image.tags[0] if c.image.tags else "unknown",
        "status": status,
        "latency_ms": tc_metrics.get("latency_ms"),
        "loss_pct": tc_metrics.get("loss_pct"),
    }


class InjectRequest(BaseModel):
    target: str
    action: str | None = None
    value: int | None = None
    latency: int | None = None
    loss: int | None = None
    duration: int | None = None


@app.post("/api/inject")
async def inject_fault(req: InjectRequest):
    has_composite = req.latency is not None or req.loss is not None
    has_legacy = req.action is not None

    if has_legacy and has_composite:
        raise HTTPException(
            status_code=400,
            detail="Cannot mix --action/--value with --latency/--loss.",
        )
    if not has_legacy and not has_composite:
        raise HTTPException(
            status_code=400,
            detail="Must specify either action or latency/loss.",
        )
    if has_legacy and req.action in ("latency", "loss") and req.value is None:
        raise HTTPException(
            status_code=400,
            detail=f"--value is required when action is '{req.action}'.",
        )

    try:
        _ = _docker_client.containers.get(req.target)
    except docker.errors.NotFound:
        raise HTTPException(
            status_code=404, detail=f"Container '{req.target}' not found."
        )

    tag = _ensure_sidecar_image()
    cmd = [
        "docker",
        "run",
        "--rm",
        "--privileged",
        "--pid=host",
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        tag,
        "--target",
        req.target,
    ]

    if has_legacy:
        cmd.extend(["--action", req.action])
        if req.value is not None:
            cmd.extend(["--value", str(req.value)])
    else:
        if req.latency is not None:
            cmd.extend(["--latency", str(req.latency)])
        if req.loss is not None:
            cmd.extend(["--loss", str(req.loss)])

    if req.duration is not None:
        cmd.extend(["--duration", str(req.duration)])

    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"status": "accepted", "target": req.target}


@app.post("/api/clear/{name}")
async def clear_container(name: str):
    try:
        _ = _docker_client.containers.get(name)
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"Container '{name}' not found.")

    tag = _ensure_sidecar_image()
    cmd = [
        "docker",
        "run",
        "--rm",
        "--privileged",
        "--pid=host",
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        tag,
        "--target",
        name,
        "--action",
        "clear",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise HTTPException(
            status_code=500, detail=result.stderr.strip() or result.stdout.strip()
        )
    return {"status": "cleared", "target": name}


class ScenarioRequest(BaseModel):
    yaml: str
    dry_run: bool = False


@app.post("/api/scenario/run")
async def run_scenario(req: ScenarioRequest):
    try:
        import yaml as _yaml

        _yaml.safe_load(req.yaml)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {exc}")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(req.yaml)
        tmp_path = f.name

    if req.dry_run:
        try:
            from injector import scenario_executor
            from io import StringIO
            import sys

            old_stdout = sys.stdout
            sys.stdout = buffer = StringIO()
            try:
                scenario_executor.dry_run(tmp_path)
            except ValueError as exc:
                sys.stdout = old_stdout
                raise HTTPException(status_code=400, detail=str(exc))
            finally:
                sys.stdout = old_stdout

            try:
                os.unlink(tmp_path)
            except OSError:
                pass

            return {"status": "validated", "output": buffer.getvalue()}
        except HTTPException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    import threading

    def _execute():
        try:
            from injector import scenario_executor

            scenario_executor.execute(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    threading.Thread(target=_execute, daemon=True).start()
    return {"status": "running"}


@app.get("/api/scenario/template")
async def scenario_template():
    template_path = Path(__file__).parent.parent / "examples" / "full-test.yaml"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Template not found.")
    return {"yaml": template_path.read_text()}
