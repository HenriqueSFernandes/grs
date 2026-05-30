"""Scenario execution engine."""

import subprocess
import sys
import time
import uuid

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
            start_times[step_id] = step.delay
            return step.delay
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
        deps = f", after: {step.after}" if step.after else ""
        delay = f", delay: {step.delay}ms" if step.delay else ""
        print(f"T+{t}ms  {step.id}  {name}  ({extra}, {step.duration}ms{deps}{delay})")


def _run_sidecar(step):
    """Launch a sidecar container for a fault step and return the Popen object."""
    tag = f"{SIDECAR_IMAGE}:{SIDECAR_VERSION}"
    container_name = f"chaos-{step.target}-{uuid.uuid4().hex[:6]}"
    cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
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

    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def execute(path: str):
    """Execute a scenario file by orchestrating sidecars."""
    scenario = load(path)

    done = set()
    running = {}
    failed = False

    print(f"Running scenario: {scenario.name or '(untitled)'}\n")

    while True:
        # Compute ready frontier
        ready = [
            s
            for s in scenario.steps
            if s.id not in done
            and s.id not in running
            and all(dep in done for dep in s.after)
        ]

        if not ready and not running:
            break

        # Sort ready steps by delay so shorter delays launch first
        ready.sort(key=lambda s: s.delay)
        current_delay = 0

        # Launch all ready steps
        for step in ready:
            if step.delay > current_delay:
                delta = step.delay - current_delay
                print(f"  [delay] Waiting {delta}ms before launching delayed steps...")
                time.sleep(delta / 1000.0)
                current_delay = step.delay
            if step.type == "wait":
                print(
                    f"  [wait] '{step.id}' ({step.name or 'no name'}) — {step.duration}ms"
                )
                time.sleep(step.duration / 1000.0)
                print(f"  [wait] '{step.id}' finished")
                done.add(step.id)
            else:
                print(
                    f"  [launch] '{step.id}' ({step.name or 'no name'}) → {step.target} — {step.duration}ms"
                )
                proc = _run_sidecar(step)
                running[step.id] = proc

        if not running:
            # Only wait steps were launched; recompute frontier
            continue

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
                    f"  [fail] Step '{step_id}' failed with exit code {retcode}.",
                    file=sys.stderr,
                )
                failed = True
                continue

            print(f"  [done] Step '{step_id}' finished")
            done.add(step_id)

        if failed:
            # Let remaining running processes finish
            while running:
                for step_id, proc in list(running.items()):
                    if proc.poll() is not None:
                        print(f"  [done] Step '{step_id}' finished (drain)")
                        del running[step_id]
                if running:
                    time.sleep(0.1)
            break

    if failed:
        print("\nScenario completed with failures.", file=sys.stderr)
        sys.exit(1)

    print("\nScenario completed successfully.")
