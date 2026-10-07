import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tempfile
import unittest
from unittest.mock import patch

from siskamling.portfolio import (
    clean_ticker,
    get_portfolio,
    set_portfolio,
    add_ticker,
    remove_ticker,
    get_all_portfolios,
    PORTFOLIO_FILE,
)

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name) / "portofolio.json"
        self.patcher = patch("siskamling.portfolio.PORTFOLIO_FILE", self.tmp_path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp_dir.cleanup()

    def test_clean_ticker(self):
        self.assertEqual(clean_ticker("bbca"), "BBCA.JK")
        self.assertEqual(clean_ticker("BBRI.JK"), "BBRI.JK")
        self.assertEqual(clean_ticker("tlkm,"), "TLKM.JK")

    def test_set_and_get_portfolio(self):
        tickers = set_portfolio("user123", ["BBRI", "BBCA.JK"])
        self.assertEqual(tickers, ["BBRI.JK", "BBCA.JK"])
        self.assertEqual(get_portfolio("user123"), ["BBRI.JK", "BBCA.JK"])

    def test_add_and_remove_ticker(self):
        set_portfolio("user123", ["BBCA"])
        updated = add_ticker("user123", "TLKM")
        self.assertIn("TLKM.JK", updated)
        self.assertIn("BBCA.JK", updated)

        removed = remove_ticker("user123", "bbca")
        self.assertEqual(removed, ["TLKM.JK"])

    def test_get_all_portfolios(self):
        set_portfolio("user1", ["BBRI"])
        set_portfolio("user2", ["ASII", "TLKM"])
        all_ports = get_all_portfolios()
        self.assertEqual(len(all_ports), 2)
        self.assertEqual(all_ports["user1"], ["BBRI.JK"])

if __name__ == '__main__':
    unittest.main()
