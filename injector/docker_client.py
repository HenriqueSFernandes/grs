"""Thin wrapper around the Docker SDK for container lookup."""

import docker
from docker.errors import NotFound


def get_container(name_or_id: str):
    """Find a running container by name or ID.

    Args:
        name_or_id: The Docker container name or short/long ID.

    Returns:
        A docker.models.containers.Container object.

    Raises:
        ValueError: If the container is not found or not running.
    """
    client = docker.from_env()

    try:
        container = client.containers.get(name_or_id)
    except NotFound as exc:
        raise ValueError(f"Container '{name_or_id}' not found.") from exc

    if container.status != "running":
        raise ValueError(
            f"Container '{name_or_id}' is not running (status: {container.status})."
        )

    return container


def get_container_pid(name_or_id: str) -> int:
    """Find a running container and return its host PID.

    Args:
        name_or_id: The Docker container name or short/long ID.

    Returns:
        The host PID (int) of the container's init process.

    Raises:
        ValueError: If the container is not found or not running.
    """
    container = get_container(name_or_id)
    pid = container.attrs.get("State", {}).get("Pid")
    if not pid:
        raise ValueError(f"Could not determine PID for container '{name_or_id}'.")
    return pid
