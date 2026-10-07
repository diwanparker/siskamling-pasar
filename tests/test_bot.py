"""Unit tests untuk runner broadcast/briefing (orkestrasi & run manifest)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from siskamling.bot import _extract_fundamental_metrics, execute_daily_broadcast, execute_morning_brief
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


class TestMorningBrief(unittest.TestCase):
    def _report(self, *, sector, market_cap, forward_pe, dividend_yield, earnings):
        return {
            "company_name": sector,
            "overview": {"sector": sector, "market_cap": market_cap},
            "valuation": {"forward_pe": forward_pe},
            "dividend": {"yield_ttm": dividend_yield},
            "financials": {"historical_financials": [{"year": 2024, "earnings": earnings}]},
        }

    @patch("siskamling.bot.dispatch_briefing")
    @patch("siskamling.bot.sectors.company_report")
    @patch("siskamling.bot.sectors.screener")
    def test_screens_and_ranks_candidates(self, mock_screener, mock_report, mock_dispatch):
        mock_screener.return_value = [{"symbol": "AAA.JK"}, {"symbol": "BBB.JK"}, {"symbol": "CCC.JK"}]
        reports = {
            "AAA.JK": self._report(sector="Banks", market_cap=1e12, forward_pe=10.0, dividend_yield=0.06, earnings=1e11),
            "BBB.JK": self._report(sector="Energy", market_cap=2e12, forward_pe=8.0, dividend_yield=0.09, earnings=5e10),
            # CCC gagal: laba negatif
            "CCC.JK": self._report(sector="Tech", market_cap=3e12, forward_pe=15.0, dividend_yield=0.10, earnings=-1e10),
        }
        mock_report.side_effect = lambda symbol, sections=None: reports[symbol]

        with tempfile.TemporaryDirectory() as tmp:
            with patch("siskamling.bot.RUNS_DIRECTORY", Path(tmp)):
                manifest = execute_morning_brief(n_candidates=1, max_pe=20, min_dividend_yield=5)

        self.assertEqual(manifest["n_universe_scanned"], 3)
        self.assertEqual(manifest["n_candidates"], 1)
        self.assertEqual(manifest["candidates"][0]["symbol"], "BBB.JK")  # yield tertinggi

        dispatched = mock_dispatch.call_args.args[1]
        self.assertEqual(dispatched[0]["symbol"], "BBB.JK")

    @patch("siskamling.bot.dispatch_briefing")
    @patch("siskamling.bot.sectors.company_report")
    @patch("siskamling.bot.sectors.screener")
    def test_rejects_overpriced_and_low_yield(self, mock_screener, mock_report, mock_dispatch):
        mock_screener.return_value = [{"symbol": "AAA.JK"}, {"symbol": "BBB.JK"}]
        reports = {
            "AAA.JK": self._report(sector="Banks", market_cap=1e12, forward_pe=40.0, dividend_yield=0.06, earnings=1e11),
            "BBB.JK": self._report(sector="Energy", market_cap=2e12, forward_pe=10.0, dividend_yield=0.02, earnings=5e10),
        }
        mock_report.side_effect = lambda symbol, sections=None: reports[symbol]

        with tempfile.TemporaryDirectory() as tmp:
            with patch("siskamling.bot.RUNS_DIRECTORY", Path(tmp)):
                manifest = execute_morning_brief(max_pe=20, min_dividend_yield=5)

        self.assertEqual(manifest["n_candidates"], 0)

    @patch("siskamling.bot.dispatch_briefing")
    @patch("siskamling.bot.sectors.screener")
    def test_screener_error_recorded(self, mock_screener, mock_dispatch):
        mock_screener.side_effect = SectorsError("boom")

        manifest = execute_morning_brief()

        self.assertEqual(manifest["n_candidates"], 0)
        self.assertEqual(manifest["n_errors"], 1)
        mock_dispatch.assert_not_called()


class TestDryRun(unittest.TestCase):
    @patch("siskamling.bot.dispatch_report")
    @patch("siskamling.bot.score_ticker")
    @patch("siskamling.bot.sectors.get")
    def test_dry_run_skips_dispatch_but_returns_messages(self, mock_get, mock_score, mock_dispatch):
        mock_get.return_value = {"top_gainers": {"1d": [{"symbol": "AAA.JK"}]}}
        mock_score.return_value = {"symbol": "AAA.JK", "score": 80, "narration": "bahaya"}

        with tempfile.TemporaryDirectory() as tmp:
            with patch("siskamling.bot.RUNS_DIRECTORY", Path(tmp)):
                manifest = execute_daily_broadcast(threshold=40, dry_run=True)

        mock_dispatch.assert_not_called()
        self.assertTrue(any("AAA" in message for message in manifest["messages"]))
        self.assertIn("bahaya", manifest["messages"])

    @patch("siskamling.bot.dispatch_report")
    @patch("siskamling.bot.sectors.get")
    def test_manifest_always_has_messages(self, mock_get, mock_dispatch):
        mock_get.return_value = {"top_gainers": {"1d": []}}

        manifest = execute_daily_broadcast()

        self.assertIn("messages", manifest)
        self.assertTrue(any("kondusif" in message for message in manifest["messages"]))


class TestFundamentalMetrics(unittest.TestCase):
    def test_picks_latest_year_earnings(self):
        report = {"financials": {"historical_financials": [{"year": 2023, "earnings": 1}, {"year": 2025, "earnings": 9}]}}
        self.assertEqual(_extract_fundamental_metrics(report)["latest_earnings"], 9)

    def test_missing_sections_do_not_crash(self):
        metrics = _extract_fundamental_metrics({})
        self.assertIsNone(metrics["forward_pe"])
        self.assertIsNone(metrics["latest_earnings"])


if __name__ == "__main__":
    unittest.main()
