"""Unit tests untuk modul siskamling.bot (CLI argument parsing & manifest generation)."""
import unittest
from unittest.mock import patch

from siskamling.bot import execute_daily_broadcast


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


if __name__ == "__main__":
    unittest.main()
