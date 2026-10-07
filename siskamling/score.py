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


# ─── Konstanta Ambang & Bobot Risiko ──────────────────────────────────
WEIGHT_MOMENTUM_5D_HIGH = 25
THRESHOLD_MOMENTUM_5D_HIGH = 0.25
WEIGHT_MOMENTUM_5D_MED = 12
THRESHOLD_MOMENTUM_5D_MED = 0.12

WEIGHT_MOMENTUM_20D_HIGH = 20
THRESHOLD_MOMENTUM_20D_HIGH = 0.60
WEIGHT_MOMENTUM_20D_MED = 10
THRESHOLD_MOMENTUM_20D_MED = 0.30

WEIGHT_VOLUME_SPIKE_HIGH = 25
THRESHOLD_VOLUME_SPIKE_HIGH = 5.0
WEIGHT_VOLUME_SPIKE_MED = 12
THRESHOLD_VOLUME_SPIKE_MED = 2.5

WEIGHT_PEAK_90D = 15
THRESHOLD_POSITION_90D = 0.90

WEIGHT_UPPER_WICK = 10
THRESHOLD_UPPER_WICK = 0.50

WEIGHT_PRICE_GAP = 5
THRESHOLD_PRICE_GAP = 0.05

MAX_RISK_SCORE = 100


def _calculate_return(current: float, base: float) -> float:
    """Hitung return persentase dari harga basis ke harga saat ini."""
    return (current / base - 1) if base > 0 else 0.0


def _calculate_upper_wick_ratio(bar: dict[str, Any]) -> float:
    """Hitung rasio panjang sumbu/ekor atas candlestick terhadap total rentang harga."""
    high = bar.get("high", 0)
    low = bar.get("low", 0)
    price_range = high - low
    if price_range <= 0:
        return 0.0
    body_top = max(bar.get("open", 0), bar.get("close", 0))
    return (high - body_top) / price_range


def _calculate_range_position(value: float, low: float, high: float) -> float:
    """Hitung posisi relatif nilai di antara batas bawah dan batas atas (0.0 - 1.0)."""
    return (value - low) / (high - low) if high > low else 0.5


def _calculate_historical_closes(recent_closes: list[float]) -> tuple[float, float]:
    """Ekstrak harga penutupan 5 hari dan 20 hari yang lalu jika tersedia."""
    close_5d = recent_closes[-6] if len(recent_closes) >= 6 else 0.0
    close_20d = recent_closes[-(HISTORY_WINDOW_DAYS + 1)] if len(recent_closes) >= (HISTORY_WINDOW_DAYS + 1) else 0.0
    return close_5d, close_20d


def extract_features(bars: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Ekstrak fitur teknikal dari deret bar harian.

    Args:
        bars: Daftar bar terurut kronologis, minimal 21 bar.

    Returns:
        Kamus fitur teknikal pada bar terakhir, atau None jika data tidak cukup.
    """
    if len(bars) < MINIMUM_BARS_REQUIRED:
        return None

    current_bar, previous_bar = bars[-1], bars[-2]
    history_bars = bars[-(HISTORY_WINDOW_DAYS + 1):-1]  # 20 hari sebelum t

    average_volume = mean(b.get("volume", 0) for b in history_bars) or 1
    recent_closes = [float(b.get("close", 0)) for b in bars]
    window_90d = bars[-LONG_TERM_WINDOW_DAYS:]

    high_90d = max(b.get("high", 0) for b in window_90d)
    low_90d = min(b.get("low", 0) for b in window_90d)

    prev_close = float(previous_bar.get("close", 0))
    current_close = float(current_bar.get("close", 0))
    close_5d_ago, close_20d_ago = _calculate_historical_closes(recent_closes)

    ret_1d = _calculate_return(current_close, prev_close)
    ret_5d = _calculate_return(current_close, close_5d_ago)
    ret_20d = _calculate_return(current_close, close_20d_ago)
    vol_ratio = current_bar.get("volume", 0) / average_volume
    price_gap = _calculate_return(float(current_bar.get("open", 0)), prev_close)
    pos_90d = _calculate_range_position(current_close, low_90d, high_90d)
    is_high_90d = current_bar.get("high", 0) >= high_90d
    upper_wick = _calculate_upper_wick_ratio(current_bar)

    feature_data = {
        "return_1d": ret_1d,
        "return_5d": ret_5d,
        "return_20d": ret_20d,
        "volume_ratio": vol_ratio,
        "price_gap": price_gap,
        "upper_wick_ratio": upper_wick,
        "position_90d": pos_90d,
        "is_at_90d_high": is_high_90d,
        # Alias pendek untuk kompatibilitas ke belakang
        "ret_1d": ret_1d,
        "ret_5d": ret_5d,
        "ret_20d": ret_20d,
        "vol_ratio": vol_ratio,
        "gap": price_gap,
        "upper_wick": upper_wick,
        "pos_90d": pos_90d,
        "at_90d_high": is_high_90d,
    }
    return feature_data


def _evaluate_momentum(features: dict[str, Any]) -> tuple[int, list[str]]:
    """Evaluasi momentum kenaikan harga 5 hari dan 20 hari."""
    score = 0
    reasons: list[str] = []

    ret_5d = features.get("return_5d", 0.0)
    if ret_5d >= THRESHOLD_MOMENTUM_5D_HIGH:
        score += WEIGHT_MOMENTUM_5D_HIGH
        reasons.append("naik >=25% dalam 5 hari")
    elif ret_5d >= THRESHOLD_MOMENTUM_5D_MED:
        score += WEIGHT_MOMENTUM_5D_MED
        reasons.append("naik >=12% dalam 5 hari")

    ret_20d = features.get("return_20d", 0.0)
    if ret_20d >= THRESHOLD_MOMENTUM_20D_HIGH:
        score += WEIGHT_MOMENTUM_20D_HIGH
        reasons.append("naik >=60% dalam 20 hari")
    elif ret_20d >= THRESHOLD_MOMENTUM_20D_MED:
        score += WEIGHT_MOMENTUM_20D_MED
        reasons.append("naik >=30% dalam 20 hari")

    return score, reasons


def _evaluate_volume(features: dict[str, Any]) -> tuple[int, list[str]]:
    """Evaluasi anomali volume perdagangan terhadap rata-rata 20 hari."""
    score = 0
    reasons: list[str] = []

    vol_ratio = features.get("volume_ratio", 0.0)
    if vol_ratio >= THRESHOLD_VOLUME_SPIKE_HIGH:
        score += WEIGHT_VOLUME_SPIKE_HIGH
        reasons.append("volume >=5x rata-rata 20 hari")
    elif vol_ratio >= THRESHOLD_VOLUME_SPIKE_MED:
        score += WEIGHT_VOLUME_SPIKE_MED
        reasons.append("volume >=2,5x rata-rata 20 hari")

    return score, reasons


def _evaluate_price_structure(features: dict[str, Any]) -> tuple[int, list[str]]:
    """Evaluasi anomali struktur candlestick (puncak 90h, rejection wick, gap)."""
    score = 0
    reasons: list[str] = []

    if features.get("is_at_90d_high") and features.get("position_90d", 0.0) >= THRESHOLD_POSITION_90D:
        score += WEIGHT_PEAK_90D
        reasons.append("di puncak 90 hari")

    if features.get("upper_wick_ratio", 0.0) >= THRESHOLD_UPPER_WICK and features.get("return_1d", 0.0) > 0:
        score += WEIGHT_UPPER_WICK
        reasons.append("ekor atas panjang (ditolak di atas)")

    if features.get("price_gap", 0.0) >= THRESHOLD_PRICE_GAP:
        score += WEIGHT_PRICE_GAP
        reasons.append("gap naik >=5%")

    return score, reasons


def calculate_risk_score(features: dict[str, Any]) -> tuple[int, list[str]]:
    """Hitung skor risiko anti-pom-pom (0-100) dan alasan pemicu.

    Args:
        features: Kamus fitur dari extract_features.

    Returns:
        Tuple (skor_terakumulasi, daftar_alasan_pemicu).
    """
    mom_score, mom_reasons = _evaluate_momentum(features)
    vol_score, vol_reasons = _evaluate_volume(features)
    struct_score, struct_reasons = _evaluate_price_structure(features)

    total_score = min(mom_score + vol_score + struct_score, MAX_RISK_SCORE)
    all_reasons = mom_reasons + vol_reasons + struct_reasons
    return total_score, all_reasons


# Alias kompatibilitas ke belakang untuk modul lama
features = extract_features
tech_score = calculate_risk_score
