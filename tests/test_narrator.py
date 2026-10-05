"""Unit tests untuk modul siskamling.narrator (grounding validator & fallback)."""
import unittest

from siskamling.narrator import (
    collect_allowed_numbers,
    generate_fallback_narration,
    validate_narration_grounding,
)


class TestNarrator(unittest.TestCase):
    def test_collect_allowed_numbers(self):
        payload = {
            "symbol": "XYZ.JK",
            "score": 85,
            "reasons": ["naik >=25% dalam 5 hari"],
            "features": {"return_1d": 0.25, "volume_ratio": 12.2},
        }
        allowed = collect_allowed_numbers(payload)
        self.assertIn("85", allowed)
        self.assertIn("25", allowed)
        self.assertIn("5", allowed)
        self.assertIn("12.2", allowed)

    def test_validate_narration_grounding_valid(self):
        payload = {
            "symbol": "BSWD.JK",
            "score": 90,
            "alasan": ["naik >=25% dalam 5 hari"],
            "features": {"ret_1d": 0.25, "vol_ratio": 12.2},
        }
        text = "Laporan BSWD.JK skor 90, naik 25% dalam 5 hari, volume 12.2x."
        is_valid, foreign = validate_narration_grounding(text, payload)
        self.assertTrue(is_valid, f"Foreign numbers: {foreign}")
        self.assertEqual(len(foreign), 0)

    def test_validate_narration_grounding_rejects_hallucination(self):
        payload = {
            "symbol": "BSWD.JK",
            "score": 90,
            "alasan": ["naik >=25% dalam 5 hari"],
        }
        text = "Laporan BSWD.JK skor 90, target harga 7500 dan dividen 18.5%."
        is_valid, foreign = validate_narration_grounding(text, payload)
        self.assertFalse(is_valid)
        self.assertIn("7500", foreign)
        self.assertIn("18.5", foreign)

    def test_generate_fallback_narration(self):
        features = {"return_1d": 0.15, "volume_ratio": 3.5}
        reasons = ["volume >=2,5x rata-rata 20 hari"]
        narration = generate_fallback_narration("UNSP.JK", 55, reasons, features)
        self.assertIn("UNSP", narration)
        self.assertIn("55/100", narration)
        self.assertIn("naik (+15.0%)", narration)
        self.assertIn("3.5x", narration)
        self.assertIn("bukan saran investasi", narration)


if __name__ == "__main__":
    unittest.main()
