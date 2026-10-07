"""Narator deterministik laporan ronda (tanpa LLM).

Prinsip:
- Perhitungan numerik 100% deterministik di modul `score.py`.
- Modul ini hanya menyusun teks laporan dari skor & fitur yang sudah dihitung.
- Format berbasis bullet point agar rapi dibaca di Telegram maupun Discord.
"""
from __future__ import annotations

from typing import Any

DISCLAIMER = "⚠️ Ini bukan saran investasi. Data dari Sectors.app."

HIGH_RISK_SCORE = 70
MEDIUM_RISK_SCORE = 40


def risk_emoji(score: int) -> str:
    """Emoji penanda tingkat risiko berdasarkan skor (0-100)."""
    if score >= HIGH_RISK_SCORE:
        return "🚨"
    if score >= MEDIUM_RISK_SCORE:
        return "🟡"
    return "🛡️"


def _feature(features: dict[str, Any], *keys: str) -> float:
    """Ambil fitur numerik pertama yang tersedia (mendukung alias panjang/pendek)."""
    for key in keys:
        value = features.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _format_signed_percent(ratio: float) -> str:
    sign = "+" if ratio >= 0 else "−"
    return f"{sign}{abs(ratio) * 100:.1f}%"


def build_alert_detail(symbol: str, score: int, reasons: list[str], features: dict[str, Any]) -> str:
    """Susun blok detail satu saham dalam bentuk bullet point yang mudah dibaca."""
    ret_1d = _feature(features, "return_1d", "ret_1d")
    ret_5d = _feature(features, "return_5d", "ret_5d")
    ret_20d = _feature(features, "return_20d", "ret_20d")
    vol_ratio = _feature(features, "volume_ratio", "vol_ratio")
    pos_90d = _feature(features, "position_90d", "pos_90d")
    at_high = bool(features.get("is_at_90d_high", features.get("at_90d_high", False)))

    position_line = f"• Posisi rentang 90 hari: {pos_90d * 100:.1f}%"
    if at_high:
        position_line += " (di puncak)"

    trigger_text = "; ".join(reasons) if reasons else "tidak ada indikasi risiko kuat"

    return "\n".join([
        f"{risk_emoji(score)} {symbol.replace('.JK', '')} — Skor Kentongan {score}/100",
        f"• Harga: {_format_signed_percent(ret_1d)} (1h) · {_format_signed_percent(ret_5d)} (5h) · {_format_signed_percent(ret_20d)} (20h)",
        f"• Volume: {vol_ratio:.1f}x rata-rata 20 hari",
        position_line,
        f"• Pemicu: {trigger_text}",
        "",
        DISCLAIMER,
    ])


def narrate(symbol: str, score: int, reasons: list[str], features: dict[str, Any]) -> str:
    """Fasade utama narasi: susun laporan deterministik dari hasil skoring."""
    return build_alert_detail(symbol, score, reasons, features)
