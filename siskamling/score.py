"""Kalkulasi skor teknikal anti-pom-pom (Lapis 1).

Aturan Desain:
- Murni deterministik tanpa LLM.
- Point-in-time: fungsi hanya menerima bar hingga hari `t` (inklusif).
- Tidak boleh mengakses bar setelah `t` (menghindari look-ahead bias).
"""
from __future__ import annotations

from statistics import mean
from typing import Any

MINIMUM_BARS_REQUIRED = 21
HISTORY_WINDOW_DAYS = 20
LONG_TERM_WINDOW_DAYS = 90


def extract_features(bars: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Ekstrak fitur teknikal dari deret bar harian.

    Args:
        bars: Daftar bar terurut kronologis, minimal 21 bar.

    Returns:
        Kamus fitur teknikal pada bar terakhir, atau None jika data tidak cukup.
    """
    if len(bars) < MINIMUM_BARS_REQUIRED:
        return None

    current_bar = bars[-1]
    previous_bar = bars[-2]
    history_bars = bars[-(HISTORY_WINDOW_DAYS + 1):-1]  # 20 hari sebelum t

    average_volume = mean(b.get("volume", 0) for b in history_bars) or 1
    recent_closes = [b.get("close", 0) for b in bars]
    window_90d = bars[-LONG_TERM_WINDOW_DAYS:]

    high_90d = max(b.get("high", 0) for b in window_90d)
    low_90d = min(b.get("low", 0) for b in window_90d)

    price_range = current_bar.get("high", 0) - current_bar.get("low", 0)
    upper_wick = (
        (current_bar.get("high", 0) - max(current_bar.get("open", 0), current_bar.get("close", 0))) / price_range
        if price_range > 0
        else 0.0
    )

    prev_close = previous_bar.get("close", 0)
    current_close = current_bar.get("close", 0)
    close_5d_ago = recent_closes[-6] if len(recent_closes) >= 6 else 0
    close_20d_ago = recent_closes[-(HISTORY_WINDOW_DAYS + 1)] if len(recent_closes) >= (HISTORY_WINDOW_DAYS + 1) else 0

    ret_1d = (current_close / prev_close - 1) if prev_close else 0.0
    ret_5d = (current_close / close_5d_ago - 1) if close_5d_ago else 0.0
    ret_20d = (current_close / close_20d_ago - 1) if close_20d_ago else 0.0
    vol_ratio = current_bar.get("volume", 0) / average_volume
    price_gap = (current_bar.get("open", 0) / prev_close - 1) if prev_close else 0.0
    pos_90d = (current_close - low_90d) / (high_90d - low_90d) if high_90d > low_90d else 0.5
    is_high_90d = current_bar.get("high", 0) >= high_90d

    return {
        "return_1d": ret_1d,
        "return_5d": ret_5d,
        "return_20d": ret_20d,
        "volume_ratio": vol_ratio,
        "price_gap": price_gap,
        "upper_wick_ratio": upper_wick,
        "position_90d": pos_90d,
        "is_at_90d_high": is_high_90d,
        # Alias pendek untuk kompatibilitas
        "ret_1d": ret_1d,
        "ret_5d": ret_5d,
        "ret_20d": ret_20d,
        "vol_ratio": vol_ratio,
        "gap": price_gap,
        "upper_wick": upper_wick,
        "pos_90d": pos_90d,
        "at_90d_high": is_high_90d,
    }


def calculate_risk_score(features: dict[str, Any]) -> tuple[int, list[str]]:
    """Hitung skor risiko anti-pom-pom (0-100) dan alasan pemicu.

    Args:
        features: Kamus fitur dari extract_features.

    Returns:
        Tuple (skor_terakumulasi, daftar_alasan_pemicu).
    """
    total_score = 0
    reasons: list[str] = []

    # Momentum 5 hari
    ret_5d = features.get("return_5d", 0.0)
    if ret_5d >= 0.25:
        total_score += 25
        reasons.append("naik >=25% dalam 5 hari")
    elif ret_5d >= 0.12:
        total_score += 12
        reasons.append("naik >=12% dalam 5 hari")

    # Momentum 20 hari
    ret_20d = features.get("return_20d", 0.0)
    if ret_20d >= 0.60:
        total_score += 20
        reasons.append("naik >=60% dalam 20 hari")
    elif ret_20d >= 0.30:
        total_score += 10
        reasons.append("naik >=30% dalam 20 hari")

    # Anomali lonjakan volume
    vol_ratio = features.get("volume_ratio", 0.0)
    if vol_ratio >= 5.0:
        total_score += 25
        reasons.append("volume >=5x rata-rata 20 hari")
    elif vol_ratio >= 2.5:
        total_score += 12
        reasons.append("volume >=2,5x rata-rata 20 hari")

    # Di puncak rentang 90 hari
    if features.get("is_at_90d_high") and features.get("position_90d", 0.0) >= 0.90:
        total_score += 15
        reasons.append("di puncak 90 hari")

    # Rejection wick atas
    if features.get("upper_wick_ratio", 0.0) >= 0.50 and features.get("return_1d", 0.0) > 0:
        total_score += 10
        reasons.append("ekor atas panjang (ditolak di atas)")

    # Gap naik saat pembukaan
    if features.get("price_gap", 0.0) >= 0.05:
        total_score += 5
        reasons.append("gap naik >=5%")

    return min(total_score, 100), reasons


# Alias kompatibilitas ke belakang untuk modul lama
features = extract_features
tech_score = calculate_risk_score
