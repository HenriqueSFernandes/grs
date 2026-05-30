"""Scenario execution engine."""

import subprocess
import sys
import time

import injector
from injector.scenario_loader import load

SIDECAR_IMAGE = "rickysf/chaos-sidecar"
SIDECAR_VERSION = injector.__version__


def dry_run(path: str):
    """Validate a scenario file and print a timeline without launching sidecars."""
    scenario = load(path)

    print(f"Scenario: {scenario.name or '(untitled)'}")
    if scenario.description:
        print(f"Description: {scenario.description}")
    print()

    # Compute start times via topological traversal
    start_times: dict[str, int] = {}

    def _compute_start(step_id: str) -> int:
        if step_id in start_times:
            return start_times[step_id]
        step = next(s for s in scenario.steps if s.id == step_id)
        if not step.after:
            start_times[step_id] = 0
            return 0
        dep_ends = []
        for dep_id in step.after:
            dep_start = _compute_start(dep_id)
            dep_step = next(s for s in scenario.steps if s.id == dep_id)
            dep_ends.append(dep_start + dep_step.duration)
        start = max(dep_ends) + step.delay
        start_times[step_id] = start
        return start

    for step in scenario.steps:
        _compute_start(step.id)

    for step in sorted(scenario.steps, key=lambda s: start_times[s.id]):
        t = start_times[step.id]
        name = step.name or step.id
        extra = f"target: {step.target}" if step.type == "fault" else "wait"
        print(f"T+{t}ms  {step.id}  {name}  ({extra}, {step.duration}ms)")


def _run_sidecar(step):
    """Launch a sidecar container for a fault step and return the Popen object."""
    tag = f"{SIDECAR_IMAGE}:{SIDECAR_VERSION}"
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
        step.target,
        "--duration",
        str(step.duration),
    ]

    for fault in step.faults:
        for action, value in fault.items():
            cmd.extend([f"--{action}", str(value)])

    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def execute(path: str):
    """Execute a scenario file by orchestrating sidecars."""
    scenario = load(path)

    done = set()
    running = {}
    failed = False

    # Initial ready frontier: steps with no dependencies
    ready = [s for s in scenario.steps if not s.after]

    while ready or running:
        # Launch all ready steps
        for step in ready:
            if step.type == "wait":
                time.sleep(step.duration / 1000.0)
                done.add(step.id)
            else:
                proc = _run_sidecar(step)
                running[step.id] = proc

        ready = []

        if not running:
            break

        # Poll running processes until at least one finishes
        while True:
            finished = []
            for step_id, proc in list(running.items()):
                ret = proc.poll()
                if ret is not None:
                    finished.append((step_id, ret))

            if finished:
                break

            time.sleep(0.1)

        # Handle finished processes
        for step_id, retcode in finished:
            del running[step_id]
            if retcode != 0:
                print(
                    f"Step '{step_id}' failed with exit code {retcode}.",
                    file=sys.stderr,
                )
                failed = True
                continue

            done.add(step_id)

        if failed:
            # Stop scheduling new steps; let running sidecars finish
            continue

        # Compute new ready frontier
        for step in scenario.steps:
            if (
                step.id in done
                or step.id in running
                or step.id in [s.id for s in ready]
            ):
                continue
            if all(dep in done for dep in step.after):
                if step.delay > 0:
                    time.sleep(step.delay / 1000.0)
                ready.append(step)

    if failed:
        print("Scenario completed with failures.", file=sys.stderr)
        sys.exit(1)
