"""Unit tests untuk modul siskamling.score."""
import unittest

from siskamling.score import calculate_risk_score, extract_features


class TestScore(unittest.TestCase):
    def test_extract_features_insufficient_bars(self):
        bars = [{"date": f"2026-09-{i:02d}", "open": 100, "high": 105, "low": 95, "close": 100, "volume": 1000} for i in range(1, 15)]
        self.assertIsNone(extract_features(bars))

    def test_extract_features_deterministic(self):
        bars = []
        for i in range(1, 30):
            bars.append({
                "date": f"2026-08-{i:02d}" if i <= 20 else f"2026-09-{i-20:02d}",
                "open": 100 + i,
                "high": 105 + i,
                "low": 98 + i,
                "close": 102 + i,
                "volume": 10000,
            })
        features = extract_features(bars)
        self.assertIsNotNone(features)
        assert features is not None
        self.assertAlmostEqual(features["volume_ratio"], 1.0, places=2)
        self.assertIn("return_1d", features)
        self.assertIn("return_5d", features)
        self.assertIn("return_20d", features)

    def test_risk_score_dormant_stock_zero(self):
        flat_features = {
            "return_1d": 0.0,
            "return_5d": 0.0,
            "return_20d": 0.0,
            "volume_ratio": 1.0,
            "price_gap": 0.0,
            "upper_wick_ratio": 0.0,
            "position_90d": 0.5,
            "is_at_90d_high": False,
        }
        score, reasons = calculate_risk_score(flat_features)
        self.assertEqual(score, 0)
        self.assertEqual(len(reasons), 0)

    def test_risk_score_explosive_pump(self):
        pump_features = {
            "return_1d": 0.25,
            "return_5d": 1.40,
            "return_20d": 1.50,
            "volume_ratio": 12.0,
            "price_gap": 0.06,
            "upper_wick_ratio": 0.0,
            "position_90d": 1.0,
            "is_at_90d_high": True,
        }
        score, reasons = calculate_risk_score(pump_features)
        self.assertGreaterEqual(score, 80)
        self.assertTrue(any(">=25%" in r for r in reasons))
        self.assertTrue(any(">=5x" in r for r in reasons))
        self.assertTrue(any("puncak 90 hari" in r for r in reasons))


if __name__ == "__main__":
    unittest.main()
