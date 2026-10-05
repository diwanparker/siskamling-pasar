"""Unit tests untuk modul siskamling.sectors (data cleaning & normalisasi)."""
import unittest

from siskamling.sectors import clean_daily_bars


class TestSectors(unittest.TestCase):
    def test_clean_daily_bars_normalizes_zero_open(self):
        raw_bars = [
            {"date": "2026-09-02", "open": 0, "high": 120, "low": 100, "close": 115, "volume": 5000},
            {"date": "2026-09-01", "open": 100, "high": 110, "low": 95, "close": 105, "volume": 8000},
        ]
        cleaned = clean_daily_bars(raw_bars)
        self.assertEqual(len(cleaned), 2)
        # Pastikan terurut tanggal
        self.assertEqual(cleaned[0]["date"], "2026-09-01")
        self.assertEqual(cleaned[1]["date"], "2026-09-02")
        # Pastikan open 0 diganti dengan close
        self.assertEqual(cleaned[1]["open"], 115)

    def test_clean_daily_bars_filters_invalid_entries(self):
        raw_bars = [
            {"date": "2026-09-01", "open": 100, "close": None, "volume": 1000},
            {"date": "2026-09-02", "open": 100, "close": 110, "volume": None},
            {"date": "2026-09-03", "open": 100, "close": 110, "volume": 0},  # Volume 0 tetap sah
        ]
        cleaned = clean_daily_bars(raw_bars)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["date"], "2026-09-03")
        self.assertEqual(cleaned[0]["volume"], 0)


if __name__ == "__main__":
    unittest.main()
