"""Skor teknikal anti-pom-pom (lapis 1). Murni deterministik, hanya OHLCV harian.

Semua fungsi menerima bar sampai hari `t` (inklusif) dan TIDAK boleh melihat bar setelahnya.
Pemanggil bertanggung jawab memotong data (lihat backtest.py, `bars[:i+1]`).
"""
from __future__ import annotations

from statistics import mean


def features(bars: list[dict]) -> dict | None:
    """bars: urut naik tanggal, minimal 21 bar. Mengembalikan fitur hari terakhir."""
    if len(bars) < 21:
        return None
    t = bars[-1]
    prev = bars[-2]
    hist = bars[-21:-1]  # 20 hari sebelum t, tanpa t
    vol_avg = mean(b["volume"] for b in hist) or 1
    closes = [b["close"] for b in bars]
    window = bars[-90:]
    hi90 = max(b["high"] for b in window)
    lo90 = min(b["low"] for b in window)
    rng = t["high"] - t["low"]
    upper_wick = (t["high"] - max(t["open"], t["close"])) / rng if rng > 0 else 0.0
    return {
        "ret_1d": t["close"] / prev["close"] - 1 if prev["close"] else 0.0,
        "ret_5d": t["close"] / closes[-6] - 1 if len(closes) >= 6 and closes[-6] else 0.0,
        "ret_20d": t["close"] / closes[-21] - 1 if closes[-21] else 0.0,
        "vol_ratio": t["volume"] / vol_avg,
        "gap": t["open"] / prev["close"] - 1 if prev["close"] else 0.0,
        "upper_wick": upper_wick,
        "pos_90d": (t["close"] - lo90) / (hi90 - lo90) if hi90 > lo90 else 0.5,
        "at_90d_high": t["high"] >= hi90,
    }


def tech_score(f: dict) -> tuple[int, list[str]]:
    """Skor 0-100 + alasan. Ambang sengaja sederhana dan terbuka (bukan hasil fitting)."""
    s, why = 0, []
    if f["ret_5d"] >= 0.25:
        s += 25; why.append("naik >=25% dalam 5 hari")
    elif f["ret_5d"] >= 0.12:
        s += 12; why.append("naik >=12% dalam 5 hari")
    if f["ret_20d"] >= 0.60:
        s += 20; why.append("naik >=60% dalam 20 hari")
    elif f["ret_20d"] >= 0.30:
        s += 10; why.append("naik >=30% dalam 20 hari")
    if f["vol_ratio"] >= 5:
        s += 25; why.append("volume >=5x rata-rata 20 hari")
    elif f["vol_ratio"] >= 2.5:
        s += 12; why.append("volume >=2,5x rata-rata 20 hari")
    if f["at_90d_high"] and f["pos_90d"] >= 0.9:
        s += 15; why.append("di puncak 90 hari")
    if f["upper_wick"] >= 0.5 and f["ret_1d"] > 0:
        s += 10; why.append("ekor atas panjang (ditolak di atas)")
    if f["gap"] >= 0.05:
        s += 5; why.append("gap naik >=5%")
    return min(s, 100), why
