"""Unit tests untuk HTTP API (FastAPI).

Dilewati otomatis bila fastapi/httpx belum terpasang, sehingga suite inti tetap
bisa dijalankan tanpa dependensi pihak ketiga.
"""
import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient

    HAVE_API = True
except ImportError:  # pragma: no cover - bergantung environment
    HAVE_API = False


@unittest.skipUnless(HAVE_API, "fastapi/httpx belum terpasang (pip install -r requirements.txt)")
class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from siskamling.api import app

        cls.client = TestClient(app)

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    @patch("siskamling.api.execute_daily_broadcast", return_value={"n_alerts": 0, "alerts": [], "messages": []})
    def test_patrol_passes_params(self, mock_execute):
        response = self.client.post("/patrol", json={"threshold": 50, "n_gainers": 10, "fetch_days": 60})
        self.assertEqual(response.status_code, 200)
        mock_execute.assert_called_once_with(threshold=50, n_gainers=10, fetch_days=60, dry_run=False)

    @patch("siskamling.api.execute_daily_broadcast", return_value={"n_alerts": 0, "messages": ["kondusif"]})
    def test_patrol_allows_empty_body(self, mock_execute):
        response = self.client.post("/patrol")
        self.assertEqual(response.status_code, 200)
        mock_execute.assert_called_once_with(threshold=None, n_gainers=None, fetch_days=None, dry_run=False)

    @patch("siskamling.api.execute_daily_broadcast", return_value={"n_alerts": 0, "messages": ["x"]})
    def test_patrol_dry_run_flag_passed(self, mock_execute):
        response = self.client.post("/patrol", json={"dry_run": True, "n_gainers": 3})
        self.assertEqual(response.status_code, 200)
        mock_execute.assert_called_once_with(threshold=None, n_gainers=3, fetch_days=None, dry_run=True)

    @patch("siskamling.api.execute_morning_brief", return_value={"n_candidates": 0, "candidates": [], "messages": []})
    def test_morning_brief_passes_params(self, mock_execute):
        response = self.client.post(
            "/morning-brief",
            json={"n_candidates": 2, "max_pe": 15, "min_dividend_yield": 6},
        )
        self.assertEqual(response.status_code, 200)
        mock_execute.assert_called_once_with(
            n_candidates=2, max_pe=15.0, min_dividend_yield=6.0, universe_size=None, dry_run=False
        )

    @patch("siskamling.api.score_ticker", return_value={"symbol": "BBCA.JK", "score": 77})
    def test_ronda_success(self, mock_score):
        response = self.client.get("/ronda/bbca")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["score"], 77)
        mock_score.assert_called_once_with("bbca")

    @patch("siskamling.api.score_ticker", return_value={"symbol": "XXXX.JK", "error": "data kurang"})
    def test_ronda_error_returns_404(self, mock_score):
        response = self.client.get("/ronda/XXXX")
        self.assertEqual(response.status_code, 404)
        self.assertIn("data kurang", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
