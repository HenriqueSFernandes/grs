"""Scenario file loader and validator."""

from dataclasses import dataclass, field

import yaml


@dataclass
class Step:
    id: str
    type: str
    duration: int
    name: str = ""
    target: str = ""
    faults: list = field(default_factory=list)
    after: list = field(default_factory=list)
    delay: int = 0


@dataclass
class Scenario:
    name: str = ""
    description: str = ""
    steps: list = field(default_factory=list)


def _validate_step(step: Step):
    """Validate a single step's schema."""
    if step.type not in ("fault", "wait"):
        raise ValueError(
            f"Step '{step.id}' has invalid type '{step.type}'. Must be 'fault' or 'wait'."
        )

    if step.duration < 0:
        raise ValueError(f"Step '{step.id}' duration must be non-negative.")

    if step.delay < 0:
        raise ValueError(f"Step '{step.id}' delay must be non-negative.")

    if step.type == "fault":
        if not step.target:
            raise ValueError(f"Fault step '{step.id}' must specify a target.")
        if not step.faults:
            raise ValueError(f"Fault step '{step.id}' must specify at least one fault.")
    elif step.type == "wait":
        if step.target:
            raise ValueError(f"Wait step '{step.id}' must not specify a target.")
        if step.faults:
            raise ValueError(f"Wait step '{step.id}' must not specify faults.")


def _validate(scenario: Scenario):
    """Enforce semantic constraints on a parsed scenario."""
    if not scenario.steps:
        raise ValueError("Scenario must contain at least one step.")

    ids = {step.id for step in scenario.steps}
    if len(ids) != len(scenario.steps):
        raise ValueError("Scenario contains duplicate step ids.")

    # after references must exist
    for step in scenario.steps:
        for dep in step.after:
            if dep not in ids:
                raise ValueError(
                    f"Step '{step.id}' references unknown id '{dep}' in after."
                )

    # cycle detection (topological sort)
    visited = set()
    stack = set()

    def _visit(step_id: str):
        if step_id in stack:
            raise ValueError("Scenario contains a dependency cycle.")
        if step_id in visited:
            return
        stack.add(step_id)
        step = next(s for s in scenario.steps if s.id == step_id)
        for dep in step.after:
            _visit(dep)
        stack.remove(step_id)
        visited.add(step_id)

    for step in scenario.steps:
        _visit(step.id)

    # concurrent same-target conflict
    # Two steps could run concurrently if there is no dependency path between them.
    # We compute reachability via DFS for each step.
    reachable: dict[str, set[str]] = {}
    for step in scenario.steps:
        stack = list(step.after)
        seen = set()
        while stack:
            dep = stack.pop()
            if dep in seen:
                continue
            seen.add(dep)
            dep_step = next(s for s in scenario.steps if s.id == dep)
            stack.extend(dep_step.after)
        reachable[step.id] = seen

    fault_steps = [s for s in scenario.steps if s.type == "fault"]
    for i, a in enumerate(fault_steps):
        for b in fault_steps[i + 1 :]:
            if a.target == b.target:
                # Check if either depends on the other
                if b.id not in reachable[a.id] and a.id not in reachable[b.id]:
                    raise ValueError(
                        f"Steps '{a.id}' and '{b.id}' target the same container "
                        f"'{a.target}' and could run concurrently."
                    )

    # clear not allowed in scenarios
    for step in scenario.steps:
        if step.type == "fault":
            for fault in step.faults:
                if "clear" in fault:
                    raise ValueError(
                        "'clear' is not allowed as a fault action inside scenarios."
                    )


def load(path: str) -> Scenario:
    """Parse a YAML scenario file and return a validated Scenario object."""
    with open(path, "r") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(
            "Scenario file must contain a YAML mapping (key-value document)."
        )

    steps_data = data.get("steps", [])
    if not isinstance(steps_data, list):
        raise ValueError("'steps' must be a list.")

    scenario = Scenario(
        name=data.get("name", ""),
        description=data.get("description", ""),
    )

    for raw in steps_data:
        if not isinstance(raw, dict):
            raise ValueError("Each step must be a mapping.")

        step = Step(
            id=raw["id"],
            type=raw["type"],
            duration=raw["duration"],
            name=raw.get("name", ""),
            target=raw.get("target", ""),
            faults=raw.get("faults", []),
            delay=raw.get("delay", 0),
        )

        after = raw.get("after", [])
        if isinstance(after, str):
            step.after = [after]
        elif not isinstance(after, list):
            raise ValueError(f"Step '{step.id}' after must be a string or list.")
        else:
            step.after = after

        _validate_step(step)
        scenario.steps.append(step)

    _validate(scenario)
    return scenario
