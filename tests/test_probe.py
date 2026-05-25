from __future__ import annotations

from unittest import TestCase

from observability import probe


class ProbeMetricsTests(TestCase):
    def setUp(self):
        with probe.STATE_LOCK:
            probe.STATE_BY_TARGET.clear()
            probe.LOSS_HISTORY_BY_TARGET.clear()

    def test_render_metrics_includes_each_target(self):
        with probe.STATE_LOCK:
            first = probe._ensure_target_state("victim")
            first.target_ip = "172.18.0.2"
            first.rtt_ms = 12.5
            first.loss_percent = 0.0
            first.successes_total = 3

            second = probe._ensure_target_state("api")
            second.target_ip = "172.18.0.3"
            second.rtt_ms = 44.2
            second.loss_percent = 25.0
            second.failures_total = 1

            probe.LOSS_HISTORY_BY_TARGET["victim"].extend([0.0, 0.0, 0.0])
            probe.LOSS_HISTORY_BY_TARGET["api"].extend([25.0])

        metrics = probe.render_metrics()

        self.assertIn('chaos_probe_up{target="api",target_ip="172.18.0.3"} 1', metrics)
        self.assertIn('chaos_probe_up{target="victim",target_ip="172.18.0.2"} 1', metrics)
        self.assertIn('chaos_probe_loss_percent_avg{target="api",target_ip="172.18.0.3"} 25.0', metrics)
        self.assertIn('chaos_probe_successes_total{target="victim",target_ip="172.18.0.2"} 3', metrics)
