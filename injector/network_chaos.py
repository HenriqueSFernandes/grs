"""Network chaos injection using tc (traffic control) via nsenter."""

import re
import subprocess


def _exec_tc_in_netns(pid: int, command: str):
    """Execute a tc command inside the target container's network namespace.

    Args:
        pid: Host PID of the target container's init process.
        command: The tc sub-command (e.g. "qdisc add dev eth0 root netem delay 500ms").

    Returns:
        subprocess.CompletedProcess result.
    """
    full_cmd = ["nsenter", "-t", str(pid), "-n", "tc"] + command.split()
    result = subprocess.run(
        full_cmd,
        capture_output=True,
        text=True,
    )
    return result


def _is_no_such_file_error(output: str) -> bool:
    """Check if tc output indicates the qdisc does not exist."""
    text = output.lower()
    return (
        "no such file" in text
        or "cannot find device" in text
        or "invalid argument" in text
        or "cannot delete qdisc with handle of zero" in text
    )


def _get_current_netem_params(pid: int) -> dict:
    """Inspect current netem parameters on eth0.

    Returns:
        A dict like {"delay": 500, "loss": 20} or {} if no netem qdisc exists.
    """
    result = _exec_tc_in_netns(pid, "qdisc show dev eth0")
    if result.returncode != 0:
        return {}

    # Look for a line like:
    # qdisc netem 8002: root refcnt 2 limit 1000 delay 500ms loss 20%
    match = re.search(r"qdisc\s+netem\s+\S+:\s+root.*", result.stdout)
    if not match:
        return {}

    line = match.group(0)
    params = {}
    delay_match = re.search(r"delay\s+(\d+)ms", line)
    if delay_match:
        params["delay"] = int(delay_match.group(1))
    loss_match = re.search(r"loss\s+(\d+(?:\.\d+)?)%", line)
    if loss_match:
        params["loss"] = float(loss_match.group(1))
    return params


def _build_netem_command(action: str, params: dict) -> str:
    """Build a tc qdisc command string from action and params.

    Args:
        action: Either "add" or "change".
        params: Dict with optional keys "delay" (int, ms) and "loss" (float, percent).

    Returns:
        Full tc sub-command string (e.g. "qdisc change dev eth0 root netem delay 500ms loss 20%").
    """
    parts = [f"qdisc {action} dev eth0 root netem"]
    if "delay" in params:
        parts.append(f"delay {int(params['delay'])}ms")
    if "loss" in params:
        parts.append(f"loss {float(params['loss'])}%")
    return " ".join(parts)


def add_composite_fault(pid: int, faults: dict):
    """Apply multiple netem faults to eth0 in a single tc invocation.

    Args:
        pid: Host PID of the target container's init process.
        faults: Dict mapping fault names to values, e.g.
                {"latency": 500, "loss": 20}.
    """
    params = {}
    if "latency" in faults:
        params["delay"] = int(faults["latency"])
    if "loss" in faults:
        params["loss"] = float(faults["loss"])

    action = "change" if _has_netem_qdisc(pid) else "add"
    cmd = _build_netem_command(action, params)
    result = _exec_tc_in_netns(pid, cmd)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to add composite fault: {result.stderr.strip()}")


def clear_rules(pid: int):
    """Remove all tc rules on eth0 inside the container's network namespace.

    This is idempotent: if no rules exist, it does not raise.
    """
    result = _exec_tc_in_netns(pid, "qdisc del dev eth0 root")
    if result.returncode != 0 and not _is_no_such_file_error(result.stderr):
        raise RuntimeError(f"Failed to clear tc rules: {result.stderr.strip()}")


def add_latency(pid: int, ms: int):
    """Add latency to all outgoing traffic on eth0.

    If a loss rule already exists, it is preserved and merged.

    Args:
        pid: Host PID of the target container's init process.
        ms: Latency in milliseconds.
    """
    if ms < 0:
        raise ValueError("Latency must be non-negative.")

    current = _get_current_netem_params(pid)
    current["delay"] = ms

    action = "change" if _has_netem_qdisc(pid) else "add"
    cmd = _build_netem_command(action, current)
    result = _exec_tc_in_netns(pid, cmd)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to add latency: {result.stderr.strip()}")


def add_loss(pid: int, percent: int):
    """Add packet loss to all outgoing traffic on eth0.

    If a latency rule already exists, it is preserved and merged.

    Args:
        pid: Host PID of the target container's init process.
        percent: Packet loss percentage (0-100).
    """
    if not 0 <= percent <= 100:
        raise ValueError("Loss percent must be between 0 and 100.")

    current = _get_current_netem_params(pid)
    current["loss"] = percent

    action = "change" if _has_netem_qdisc(pid) else "add"
    cmd = _build_netem_command(action, current)
    result = _exec_tc_in_netns(pid, cmd)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to add loss: {result.stderr.strip()}")


def _has_netem_qdisc(pid: int) -> bool:
    """Check if a netem qdisc currently exists on eth0."""
    result = _exec_tc_in_netns(pid, "qdisc show dev eth0")
    return result.returncode == 0 and "netem" in result.stdout
