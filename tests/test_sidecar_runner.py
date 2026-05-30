"""Tests for injector.sidecar_runner (host CLI)."""

import sys
import tempfile
from unittest.mock import MagicMock, patch


from injector import sidecar_runner


class TestDurationForwarding:
    """chaosctl forwards --duration to the sidecar."""

    @patch("injector.sidecar_runner._ensure_image")
    @patch("injector.sidecar_runner.subprocess.run")
    def test_duration_is_forwarded_to_sidecar(self, mock_run, mock_ensure_image):
        mock_ensure_image.return_value = "rickysf/chaos-sidecar:0.2.0"
        mock_run.return_value = MagicMock(returncode=0)

        with patch.object(
            sys,
            "argv",
            [
                "chaosctl",
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
            sidecar_runner.main()

        mock_ensure_image.assert_called_once()
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "--duration" in cmd
        assert "3000" in cmd
        assert cmd.index("--duration") + 1 == cmd.index("3000")

    @patch("injector.sidecar_runner._ensure_image")
    @patch("injector.sidecar_runner.subprocess.run")
    def test_duration_absent_when_not_specified(self, mock_run, mock_ensure_image):
        mock_ensure_image.return_value = "rickysf/chaos-sidecar:0.2.0"
        mock_run.return_value = MagicMock(returncode=0)

        with patch.object(
            sys,
            "argv",
            [
                "chaosctl",
                "--target",
                "victim",
                "--action",
                "latency",
                "--value",
                "500",
            ],
        ):
            sidecar_runner.main()

        mock_ensure_image.assert_called_once()
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "--duration" not in cmd


class TestRunSubcommand:
    """chaosctl run <scenario.yaml> subcommand."""

    @patch("injector.sidecar_runner.scenario_executor.dry_run")
    def test_run_dry_run_invokes_dry_run(self, mock_dry_run):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("name: test\nsteps: []\n")
            f.flush()
            with patch.object(
                sys,
                "argv",
                [
                    "chaosctl",
                    "run",
                    "--dry-run",
                    f.name,
                ],
            ):
                sidecar_runner.main()

        mock_dry_run.assert_called_once_with(f.name)
