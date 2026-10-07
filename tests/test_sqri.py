import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from siskamling.score import (
    calculate_risk_score,
    extract_features,
    calculate_volume_zscore,
)


class TestSQRIEngine(unittest.TestCase):
    def test_calculate_volume_zscore(self):
        # 20 flat volumes of 100, then current volume of 400
        history = [100.0] * 20
        z = calculate_volume_zscore(400.0, history)
        # Standard deviation of identical values is handled gracefully
        self.assertGreater(z, 0)

        # Diverse history: mean ~ 100, stdev ~ 10
        history_diverse = [90.0, 110.0] * 10
        z_spike = calculate_volume_zscore(150.0, history_diverse)
        self.assertGreater(z_spike, 3.0)

    def test_junk_stock_pump_penalty(self):
        # Technical momentum + volume spike on a loss-making micro-cap
        features = {
            "return_1d": 0.20,
            "return_5d": 0.35,
            "return_20d": 0.50,
            "volume_ratio": 4.0,
            "volume_zscore": 3.2,
            "price_gap": 0.08,
            "upper_wick_ratio": 0.40,
            "position_90d": 0.95,
            "is_at_90d_high": True,
        }
        fundamental = {
            "market_cap_billion": 300,  # Micro-cap < 1T
            "pe": -15.0,  # Merugi (Negative PE)
            "is_loss_making": True,
        }
        score, reasons = calculate_risk_score(features, fundamental=fundamental)
        self.assertGreaterEqual(score, 75)
        self.assertTrue(any("merugi" in r.lower() or "junk" in r.lower() or "kapitalisasi mikro" in r.lower() for r in reasons))

    def test_bluechip_false_positive_relief(self):
        # Strong volume and momentum on a solid, highly profitable big-cap bank
        features = {
            "return_1d": 0.04,
            "return_5d": 0.15,
            "return_20d": 0.25,
            "volume_ratio": 3.0,
            "volume_zscore": 2.2,
            "price_gap": 0.01,
            "upper_wick_ratio": 0.10,
            "position_90d": 0.70,
            "is_at_90d_high": False,
        }
        fundamental = {
            "market_cap_billion": 650000,  # Big-cap 650T
            "pe": 12.5,  # Valuasi sehat
            "dividend_yield": 4.8,  # Dividen tinggi
            "is_loss_making": False,
        }
        score, reasons = calculate_risk_score(features, fundamental=fundamental)
        # Should NOT trigger high risk alert for bluechip accumulation
        self.assertLess(score, 40)
        self.assertTrue(any("bluechip" in r.lower() or "sehat" in r.lower() for r in reasons))

    def test_market_divergence_anomaly(self):
        features = {
            "return_1d": 0.18,
            "return_5d": 0.20,
            "return_20d": 0.25,
            "volume_ratio": 3.5,
            "price_gap": 0.05,
            "upper_wick_ratio": 0.20,
            "position_90d": 0.85,
            "is_at_90d_high": True,
        }
        # IHSG is crashing down -1.5%
        score, reasons = calculate_risk_score(features, market_return=-0.015)
        self.assertTrue(any("melawan arah ihsg" in r.lower() or "divergence" in r.lower() for r in reasons))

    def test_backward_compatibility_without_fundamental(self):
        features = {
            "return_1d": 0.10,
            "return_5d": 0.28,
            "return_20d": 0.65,
            "volume_ratio": 5.5,
            "price_gap": 0.06,
            "upper_wick_ratio": 0.55,
            "position_90d": 0.95,
            "is_at_90d_high": True,
        }
        score, reasons = calculate_risk_score(features)
        self.assertIsInstance(score, int)
        self.assertGreater(score, 50)
        self.assertIsInstance(reasons, list)


if __name__ == "__main__":
    unittest.main()