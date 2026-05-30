"""Metrics server that runs inside the sidecar container.

Queries tc rules and runs pings from each target container's network namespace.
Exposed as a FastAPI app, launched with --action monitor.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

import docker
from fastapi import FastAPI, HTTPException

from injector.docker_client import get_container_pid
from injector.network_chaos import _get_current_netem_params, ping_from_namespace

app = FastAPI(title="Chaos Monitor", version="0.1.0")

_client = docker.from_env()


def _running_containers() -> list["docker.models.containers.Container"]:
    return [c for c in _client.containers.list() if c.status == "running"]


def _container_ip(container: "docker.models.containers.Container") -> str | None:
    attrs = container.attrs
    networks = attrs.get("NetworkSettings", {}).get("Networks", {})
    if not networks:
        return None
    first = next(iter(networks.values()))
    return first.get("IPAddress")


def _container_networks(
    container: "docker.models.containers.Container",
) -> dict[str, str]:
    attrs = container.attrs
    networks = attrs.get("NetworkSettings", {}).get("Networks", {})
    return {
        name: data.get("IPAddress")
        for name, data in networks.items()
        if data.get("IPAddress")
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/metrics/all")
async def metrics_all():
    result = {}
    for c in _running_containers():
        try:
            pid = get_container_pid(c.name)
            params = _get_current_netem_params(pid)
        except Exception:
            params = {}
        result[c.name] = {
            "latency_ms": params.get("delay"),
            "loss_pct": params.get("loss"),
            "ip": _container_ip(c),
        }
    return result


@app.get("/metrics/{name}")
async def metrics_one(name: str):
    try:
        pid = get_container_pid(name)
        params = _get_current_netem_params(pid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    container = _client.containers.get(name)
    return {
        "name": name,
        "latency_ms": params.get("delay"),
        "loss_pct": params.get("loss"),
        "ip": _container_ip(container),
    }


@app.get("/ping/all")
async def ping_all():
    containers = _running_containers()
    net_map = {c.name: _container_networks(c) for c in containers}

    results = {}

    def _ping_one(src_name: str, src_pid: int, dst_name: str, dst_ip: str):
        r = ping_from_namespace(src_pid, dst_ip)
        return (src_name, dst_name, r)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = []
        for src_c in containers:
            try:
                src_pid = get_container_pid(src_c.name)
            except Exception:
                continue
            src_networks = net_map.get(src_c.name, {})
            if not src_networks:
                continue
            for dst_name, dst_networks in net_map.items():
                if dst_name == src_c.name:
                    continue
                shared = set(src_networks).intersection(dst_networks)
                if not shared:
                    continue
                net_name = next(iter(shared))
                dst_ip = dst_networks.get(net_name)
                if not dst_ip:
                    continue
                futures.append(
                    pool.submit(_ping_one, src_c.name, src_pid, dst_name, dst_ip)
                )

        for future in as_completed(futures):
            try:
                src, dst, r = future.result()
            except Exception:
                continue
            key = f"{src}→{dst}"
            results[key] = r

    return results


@app.get("/ping/{name}")
async def ping_one(name: str):
    try:
        pid = get_container_pid(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    containers = _running_containers()
    results = {}
    src_networks = {}
    for c in containers:
        if c.name == name:
            src_networks = _container_networks(c)
            break
    if not src_networks:
        return results
    for dst in containers:
        if dst.name == name:
            continue
        dst_networks = _container_networks(dst)
        shared = set(src_networks).intersection(dst_networks)
        if not shared:
            continue
        net_name = next(iter(shared))
        dst_ip = dst_networks.get(net_name)
        if not dst_ip:
            continue
        results[dst.name] = ping_from_namespace(pid, dst_ip)

    return results
