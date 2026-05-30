"""Tests for scenario dry-run timeline."""

import tempfile
from unittest.mock import MagicMock, patch

import pytest

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


class TestSequentialExecution:
    """Scenario scheduler runs steps in DAG order."""

    @patch("injector.scenario_executor._run_sidecar")
    def test_sequential_steps_run_in_order(self, mock_run_sidecar):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_run_sidecar.return_value = mock_proc
        yaml = """
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
            scenario_executor.execute(f.name)

        assert mock_run_sidecar.call_count == 2
        first_call = mock_run_sidecar.call_args_list[0]
        second_call = mock_run_sidecar.call_args_list[1]
        assert first_call.args[0].id == "s1"
        assert second_call.args[0].id == "s2"

    @patch("injector.scenario_executor.time.sleep")
    @patch("injector.scenario_executor._run_sidecar")
    def test_step_with_delay_sleeps_before_launch(self, mock_run_sidecar, mock_sleep):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_run_sidecar.return_value = mock_proc
        yaml = """
steps:
  - id: s1
    type: fault
    target: c1
    duration: 1000
    faults:
      - loss: 10
  - id: s2
    type: fault
    target: c2
    duration: 1000
    after: [s1]
    delay: 500
    faults:
      - latency: 200
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            scenario_executor.execute(f.name)

        mock_sleep.assert_called_once_with(0.5)
        assert mock_run_sidecar.call_count == 2

    @patch("injector.scenario_executor.time.sleep")
    @patch("injector.scenario_executor._run_sidecar")
    def test_wait_step_blocks_locally(self, mock_run_sidecar, mock_sleep):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_run_sidecar.return_value = mock_proc
        yaml = """
steps:
  - id: s1
    type: fault
    target: c1
    duration: 1000
    faults:
      - loss: 10
  - id: pause
    type: wait
    duration: 500
    after: [s1]
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            scenario_executor.execute(f.name)

        mock_sleep.assert_called_once_with(0.5)
        # wait step does not launch a sidecar
        assert mock_run_sidecar.call_count == 1

    @patch("injector.scenario_executor._run_sidecar")
    def test_failure_stops_scheduling(self, mock_run_sidecar):
        mock_proc_ok = MagicMock()
        mock_proc_ok.poll.return_value = 0
        mock_proc_fail = MagicMock()
        mock_proc_fail.poll.return_value = 1
        mock_run_sidecar.side_effect = [mock_proc_fail, mock_proc_ok]
        yaml = """
steps:
  - id: s1
    type: fault
    target: c1
    duration: 1000
    faults:
      - loss: 10
  - id: s2
    type: fault
    target: c2
    duration: 1000
    after: [s1]
    faults:
      - latency: 200
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            with pytest.raises(SystemExit) as exc_info:
                scenario_executor.execute(f.name)
            assert exc_info.value.code == 1

        # Only s1 launched; s2 never started because s1 failed
        assert mock_run_sidecar.call_count == 1


class TestParallelExecution:
    """Steps with no dependencies run concurrently."""

    @patch("injector.scenario_executor._run_sidecar")
    def test_parallel_steps_launch_together(self, mock_run_sidecar):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_run_sidecar.return_value = mock_proc
        yaml = """
steps:
  - id: s1
    type: fault
    target: c1
    duration: 5000
    faults:
      - loss: 10
  - id: s2
    type: fault
    target: c2
    duration: 3000
    faults:
      - latency: 200
  - id: s3
    type: fault
    target: c3
    duration: 2000
    after: [s1, s2]
    faults:
      - latency: 100
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            scenario_executor.execute(f.name)

        # s1 and s2 launched together (frontier 1), then s3 (frontier 2)
        assert mock_run_sidecar.call_count == 3
        first_batch = [call.args[0].id for call in mock_run_sidecar.call_args_list[:2]]
        assert sorted(first_batch) == ["s1", "s2"]
        assert mock_run_sidecar.call_args_list[2].args[0].id == "s3"

    @patch("injector.scenario_executor.time.sleep")
    @patch("injector.scenario_executor._run_sidecar")
    def test_parallel_with_delay_and_wait(self, mock_run_sidecar, mock_sleep):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_run_sidecar.return_value = mock_proc
        yaml = """
steps:
  - id: s1
    type: fault
    target: c1
    duration: 1000
    faults:
      - loss: 10
  - id: s2
    type: fault
    target: c2
    duration: 1000
    faults:
      - latency: 200
  - id: pause
    type: wait
    duration: 500
    after: [s1, s2]
  - id: s3
    type: fault
    target: c3
    duration: 1000
    after: [pause]
    delay: 300
    faults:
      - latency: 100
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml)
            f.flush()
            scenario_executor.execute(f.name)

        assert mock_run_sidecar.call_count == 3
        # wait step sleeps locally
        mock_sleep.assert_any_call(0.5)
        # delay before s3
        mock_sleep.assert_any_call(0.3)
