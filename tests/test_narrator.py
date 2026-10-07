"""Unit tests untuk modul siskamling.narrator (narasi deterministik)."""
import unittest

from siskamling.narrator import build_alert_detail, narrate, risk_emoji


class TestRiskEmoji(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(risk_emoji(70), "🚨")
        self.assertEqual(risk_emoji(40), "🟡")
        self.assertEqual(risk_emoji(39), "🛡️")


class TestNarration(unittest.TestCase):
    def test_narrate_includes_symbol_score_and_metrics(self):
        features = {"return_1d": 0.15, "return_5d": 0.30, "return_20d": 0.45, "volume_ratio": 3.5, "position_90d": 0.9}
        reasons = ["volume >=2,5x rata-rata 20 hari"]
        narration = narrate("UNSP.JK", 55, reasons, features)

        self.assertIn("UNSP", narration)
        self.assertIn("55/100", narration)
        self.assertIn("+15.0% (1h)", narration)
        self.assertIn("3.5x rata-rata 20 hari", narration)
        self.assertIn("• Pemicu: volume >=2,5x rata-rata 20 hari", narration)
        self.assertIn("bukan saran investasi", narration)
        self.assertNotIn(".JK", narration)

    def test_narrate_supports_short_feature_aliases(self):
        features = {"ret_1d": -0.05, "vol_ratio": 2.0}
        narration = build_alert_detail("BBCA.JK", 20, [], features)

        self.assertIn("−5.0% (1h)", narration)
        self.assertIn("2.0x rata-rata 20 hari", narration)
        self.assertIn("tidak ada indikasi risiko kuat", narration)

    def test_narrate_marks_ninety_day_high(self):
        features = {"position_90d": 1.0, "is_at_90d_high": True}
        narration = narrate("AAAA.JK", 80, ["di puncak 90 hari"], features)
        self.assertIn("(di puncak)", narration)
        self.assertTrue(narration.startswith("🚨"))


if __name__ == "__main__":
    unittest.main()
