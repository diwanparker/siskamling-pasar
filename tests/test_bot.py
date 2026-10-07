"""Unit tests untuk runner broadcast (orkestrasi & run manifest)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from siskamling.bot import execute_daily_broadcast
from siskamling.sectors import SectorsError


class TestBroadcastManifest(unittest.TestCase):
    @patch("siskamling.bot.dispatch_report")
    @patch("siskamling.bot.sectors.get")
    def test_execute_daily_broadcast_custom_params_and_manifest(self, mock_sectors_get, mock_dispatch):
        mock_sectors_get.return_value = {"top_gainers": {"1d": []}}

        manifest = execute_daily_broadcast(threshold=50, n_gainers=15, fetch_days=60)

        self.assertIsInstance(manifest, dict)
        self.assertIn("run_id", manifest)
        self.assertIn("started_at", manifest)
        self.assertIn("finished_at", manifest)
        self.assertEqual(manifest["n_gainers_scanned"], 0)
        self.assertEqual(manifest["n_alerts"], 0)
        mock_dispatch.assert_not_called()

        args, _ = mock_sectors_get.call_args
        self.assertEqual(args[0], "/v2/companies/top-changes/")
        self.assertEqual(args[1]["n_stock"], 15)

    @patch("siskamling.bot.dispatch_report")
    @patch("siskamling.bot.score_ticker")
    @patch("siskamling.bot.sectors.get")
    def test_execute_daily_broadcast_dispatches_triggered_alerts(self, mock_sectors_get, mock_score, mock_dispatch):
        mock_sectors_get.return_value = {"top_gainers": {"1d": [{"symbol": "AAA.JK"}]}}
        mock_score.return_value = {"symbol": "AAA.JK", "score": 80, "narration": "bahaya"}

        with tempfile.TemporaryDirectory() as tmp:
            with patch("siskamling.bot.RUNS_DIRECTORY", Path(tmp)):
                manifest = execute_daily_broadcast(threshold=40)

        self.assertEqual(manifest["n_alerts"], 1)
        self.assertEqual(manifest["alerts"], [{"symbol": "AAA.JK", "score": 80}])

        dispatched_alerts = mock_dispatch.call_args.args[1]
        self.assertEqual(dispatched_alerts[0]["symbol"], "AAA.JK")

    @patch("siskamling.bot.dispatch_report")
    @patch("siskamling.bot.sectors.get")
    def test_execute_daily_broadcast_records_fetch_error(self, mock_sectors_get, mock_dispatch):
        mock_sectors_get.side_effect = SectorsError("boom")

        manifest = execute_daily_broadcast()

        self.assertEqual(manifest["n_gainers_scanned"], 0)
        self.assertEqual(manifest["n_alerts"], 0)
        self.assertEqual(manifest["n_errors"], 1)


if __name__ == "__main__":
    unittest.main()
