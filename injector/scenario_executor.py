"""Scenario execution engine."""

from injector.scenario_loader import load


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
