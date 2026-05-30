"""Tests for injector.cli (sidecar entry point)."""

import sys
from unittest.mock import patch


from injector import cli


class TestDuration:
    """Sidecar auto-clears after --duration milliseconds."""

    @patch("injector.cli.time.sleep")
    @patch("injector.cli.clear_rules")
    @patch("injector.cli.add_latency")
    @patch("injector.cli.get_container_pid")
    def test_latency_with_duration_sleeps_then_clears(
        self, mock_get_pid, mock_add_latency, mock_clear, mock_sleep
    ):
        mock_get_pid.return_value = 1234

        with patch.object(
            sys,
            "argv",
            [
                "chaos",
                "--target",
                "victim",
                "--action",
                "latency",
                "--value",
                "500",
                "--duration",
                "3000",
            ],
        ):
            cli.main()

        mock_get_pid.assert_called_once_with("victim")
        mock_add_latency.assert_called_once_with(1234, 500)
        mock_sleep.assert_called_once_with(3.0)
        mock_clear.assert_called_once_with(1234)

    @patch("injector.cli.time.sleep")
    @patch("injector.cli.clear_rules")
    @patch("injector.cli.add_loss")
    @patch("injector.cli.get_container_pid")
    def test_loss_with_duration_sleeps_then_clears(
        self, mock_get_pid, mock_add_loss, mock_clear, mock_sleep
    ):
        mock_get_pid.return_value = 1234

        with patch.object(
            sys,
            "argv",
            [
                "chaos",
                "--target",
                "victim",
                "--action",
                "loss",
                "--value",
                "20",
                "--duration",
                "1500",
            ],
        ):
            cli.main()

        mock_get_pid.assert_called_once_with("victim")
        mock_add_loss.assert_called_once_with(1234, 20)
        mock_sleep.assert_called_once_with(1.5)
        mock_clear.assert_called_once_with(1234)

    @patch("injector.cli.time.sleep")
    @patch("injector.cli.clear_rules")
    @patch("injector.cli.add_latency")
    @patch("injector.cli.get_container_pid")
    def test_latency_without_duration_does_not_sleep_or_clear(
        self, mock_get_pid, mock_add_latency, mock_clear, mock_sleep
    ):
        mock_get_pid.return_value = 1234

        with patch.object(
            sys,
            "argv",
            [
                "chaos",
                "--target",
                "victim",
                "--action",
                "latency",
                "--value",
                "500",
            ],
        ):
            cli.main()

        mock_get_pid.assert_called_once_with("victim")
        mock_add_latency.assert_called_once_with(1234, 500)
        mock_sleep.assert_not_called()
        mock_clear.assert_not_called()

    @patch("injector.cli.time.sleep")
    @patch("injector.cli.clear_rules")
    @patch("injector.cli.get_container_pid")
    def test_clear_action_ignores_duration(self, mock_get_pid, mock_clear, mock_sleep):
        """--duration has no effect when action is clear."""
        mock_get_pid.return_value = 1234

        with patch.object(
            sys,
            "argv",
            [
                "chaos",
                "--target",
                "victim",
                "--action",
                "clear",
                "--duration",
                "3000",
            ],
        ):
            cli.main()

        mock_get_pid.assert_called_once_with("victim")
        mock_clear.assert_called_once_with(1234)
        mock_sleep.assert_not_called()


class TestCompositeFaults:
    """Multiple faults applied in a single tc invocation."""

    @patch("injector.cli.time.sleep")
    @patch("injector.cli.clear_rules")
    @patch("injector.cli.add_composite_fault")
    @patch("injector.cli.get_container_pid")
    def test_applies_latency_and_loss_together(
        self, mock_get_pid, mock_add_composite, mock_clear, mock_sleep
    ):
        mock_get_pid.return_value = 1234

        with patch.object(
            sys,
            "argv",
            [
                "chaos",
                "--target",
                "victim",
                "--latency",
                "500",
                "--loss",
                "20",
                "--duration",
                "3000",
            ],
        ):
            cli.main()

        mock_get_pid.assert_called_once_with("victim")
        mock_add_composite.assert_called_once_with(1234, {"latency": 500, "loss": 20})
        mock_sleep.assert_called_once_with(3.0)
        mock_clear.assert_called_once_with(1234)
