"""Tests for scenario dry-run timeline."""

import tempfile
from unittest.mock import patch

from injector import scenario_executor


class TestDryRunTimeline:
    """--dry-run prints a timeline without launching sidecars."""

    def test_prints_timeline_for_parallel_steps(self):
        yaml = """
name: "Parallel test"
steps:
  - id: s1
    name: "Loss on c1"
    type: fault
    target: c1
    duration: 5000
    faults:
      - loss: 50
  - id: s2
    name: "Latency on c2"
    type: fault
    target: c2
    duration: 3000
    faults:
      - latency: 500
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            with patch("builtins.print") as mock_print:
                scenario_executor.dry_run(f.name)

        printed = [call.args[0] for call in mock_print.call_args_list if call.args]
        assert any("T+0ms" in line for line in printed)
        assert any("s1" in line for line in printed)
        assert any("s2" in line for line in printed)

    def test_prints_timeline_for_sequential_steps(self):
        yaml = """
name: "Sequential test"
steps:
  - id: s1
    type: fault
    target: c1
    duration: 3000
    faults:
      - loss: 10
  - id: s2
    type: fault
    target: c2
    duration: 2000
    after: [s1]
    faults:
      - latency: 200
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            with patch("builtins.print") as mock_print:
                scenario_executor.dry_run(f.name)

        printed = [call.args[0] for call in mock_print.call_args_list if call.args]
        assert any("T+0ms" in line and "s1" in line for line in printed)
        assert any("T+3000ms" in line and "s2" in line for line in printed)

    def test_dry_run_does_not_launch_sidecars(self):
        yaml = """
steps:
  - id: s1
    type: fault
    target: c1
    duration: 1000
    faults:
      - loss: 10
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            with patch("injector.scenario_executor.subprocess.run") as mock_run:
                scenario_executor.dry_run(f.name)
            mock_run.assert_not_called()
