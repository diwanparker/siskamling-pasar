"""Unit tests untuk modul siskamling.bot (CLI argument parsing, manifest generation & notification sinks)."""
import unittest
from unittest.mock import MagicMock, patch

from siskamling.bot import dispatch_telegram_alerts, execute_daily_broadcast


class TestBot(unittest.TestCase):
    @patch("siskamling.bot.get_telegram_chat_id", return_value="")
    @patch("siskamling.bot.sectors.get")
    def test_execute_daily_broadcast_custom_params_and_manifest(self, mock_sectors_get, mock_chat_id):
        mock_sectors_get.return_value = {
            "top_gainers": {
                "1d": []
            }
        }
        manifest = execute_daily_broadcast(threshold=50, n_gainers=15, fetch_days=60)
        self.assertIsInstance(manifest, dict)
        self.assertIn("run_id", manifest)
        self.assertIn("started_at", manifest)
        self.assertIn("finished_at", manifest)
        self.assertEqual(manifest["n_gainers_scanned"], 0)
        self.assertEqual(manifest["n_alerts"], 0)

        # Verifikasi sectors.get dipanggil dengan n_stock=15
        mock_sectors_get.assert_called_once()
        args, kwargs = mock_sectors_get.call_args
        self.assertEqual(args[0], "/v2/companies/top-changes/")
        self.assertEqual(args[1]["n_stock"], 15)

    @patch("siskamling.bot.send_message")
    def test_dispatch_telegram_alerts_empty_chat_id(self, mock_send):
        dispatch_telegram_alerts([], chat_id="")
        mock_send.assert_not_called()

    @patch("siskamling.bot.send_message")
    def test_dispatch_telegram_alerts_safe_market(self, mock_send):
        dispatch_telegram_alerts([], chat_id="12345")
        mock_send.assert_called_once()
        args, _ = mock_send.call_args
        self.assertEqual(args[0], "12345")
        self.assertIn("Laporan Ronda Sore", args[1])
        self.assertIn("kondusif", args[1])

    @patch("siskamling.bot.time.sleep")
    @patch("siskamling.bot.send_message")
    def test_dispatch_telegram_alerts_with_alerts(self, mock_send, mock_sleep):
        sample_alerts = [
            {"symbol": "TEST.JK", "score": 85, "narration": "Laporan bahaya saham TEST"}
        ]
        dispatch_telegram_alerts(sample_alerts, chat_id="12345")
        self.assertEqual(mock_send.call_count, 2)  # 1 header + 1 alert narration


if __name__ == "__main__":
    unittest.main()
