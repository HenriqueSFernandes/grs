"""Tests for injector.network_chaos."""

from unittest.mock import MagicMock, patch

import pytest

from injector import network_chaos


class TestCompositeFaultValidation:
    """add_composite_fault validates input ranges."""

    @patch("injector.network_chaos._has_netem_qdisc")
    @patch("injector.network_chaos._exec_in_netns")
    def test_rejects_negative_latency(self, mock_exec, mock_has):
        mock_has.return_value = False
        mock_exec.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with pytest.raises(ValueError, match="non-negative"):
            network_chaos.add_composite_fault(1234, {"latency": -10})

    @patch("injector.network_chaos._has_netem_qdisc")
    @patch("injector.network_chaos._exec_in_netns")
    def test_rejects_negative_loss(self, mock_exec, mock_has):
        mock_has.return_value = False
        mock_exec.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with pytest.raises(ValueError, match="0 and 100"):
            network_chaos.add_composite_fault(1234, {"loss": -5})

    @patch("injector.network_chaos._has_netem_qdisc")
    @patch("injector.network_chaos._exec_in_netns")
    def test_rejects_loss_over_100(self, mock_exec, mock_has):
        mock_has.return_value = False
        mock_exec.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with pytest.raises(ValueError, match="0 and 100"):
            network_chaos.add_composite_fault(1234, {"loss": 150})

    @patch("injector.network_chaos._has_netem_qdisc")
    @patch("injector.network_chaos._exec_in_netns")
    def test_accepts_valid_composite_fault(self, mock_exec, mock_has):
        mock_has.return_value = False
        mock_exec.return_value = MagicMock(returncode=0, stdout="", stderr="")

        network_chaos.add_composite_fault(1234, {"latency": 500, "loss": 20})

        mock_exec.assert_called_once()
        cmd = " ".join(mock_exec.call_args[0][1])
        assert "netem" in cmd
        assert "delay 500ms" in cmd
        assert "loss 20.0%" in cmd
