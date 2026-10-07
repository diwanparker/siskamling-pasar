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


from dataclasses import dataclass


@dataclass(frozen=True)
class StockAlert:
    """Objek parameter untuk satu peringatan saham terdeteksi."""

    symbol: str
    score: int
    reasons: list[str]
    features: dict[str, Any]


def build_alert_detail(
    symbol: str | StockAlert,
    score: int | None = None,
    reasons: list[str] | None = None,
    features: dict[str, Any] | None = None,
) -> str:
    """Susun blok detail satu saham dalam bentuk bullet point yang mudah dibaca."""
    if isinstance(symbol, StockAlert):
        target_symbol = symbol.symbol
        target_score = symbol.score
        target_reasons = symbol.reasons
        target_features = symbol.features
    else:
        target_symbol = symbol
        target_score = score or 0
        target_reasons = reasons or []
        target_features = features or {}

    ret_1d = _feature(target_features, "return_1d", "ret_1d")
    ret_5d = _feature(target_features, "return_5d", "ret_5d")
    ret_20d = _feature(target_features, "return_20d", "ret_20d")
    vol_ratio = _feature(target_features, "volume_ratio", "vol_ratio")
    vol_zscore = target_features.get("volume_zscore")
    pos_90d = _feature(target_features, "position_90d", "pos_90d")
    at_high = bool(target_features.get("is_at_90d_high", target_features.get("at_90d_high", False)))

    position_line = f"• Posisi rentang 90 hari: {pos_90d * 100:.1f}%"
    if at_high:
        position_line += " (di puncak)"

    vol_line = f"• Volume: {vol_ratio:.1f}x rata-rata 20 hari"
    if isinstance(vol_zscore, (int, float)):
        vol_line += f" (Z-Score {vol_zscore:+.1f}σ)"

    trigger_text = "; ".join(target_reasons) if target_reasons else "tidak ada indikasi risiko kuat"

    return "\n".join([
        f"{risk_emoji(target_score)} {target_symbol.replace('.JK', '')} — Skor Kentongan {target_score}/100",
        f"• Harga: {_format_signed_percent(ret_1d)} (1h) · {_format_signed_percent(ret_5d)} (5h) · {_format_signed_percent(ret_20d)} (20h)",
        vol_line,
        position_line,
        f"• Pemicu: {trigger_text}",
        "",
        DISCLAIMER,
    ])


def narrate(
    symbol: str | StockAlert,
    score: int | None = None,
    reasons: list[str] | None = None,
    features: dict[str, Any] | None = None,
) -> str:
    """Fasade utama narasi: susun laporan deterministik dari hasil skoring."""
    return build_alert_detail(symbol, score, reasons, features)


# ─── Narasi Briefing Pagi (screening fundamental) ──────────────────

def _format_trillion(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"Rp {value / 1_000_000_000_000:.2f} T"


def _format_multiple(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{value:.1f}x"


def _format_ratio_percent(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{value * 100:.1f}%"


def narrate_candidate(symbol: str, metrics: dict[str, Any]) -> str:
    """Susun blok detail satu kandidat fundamental (deterministik, tanpa LLM)."""
    name = metrics.get("company_name") or symbol.replace(".JK", "")
    return "\n".join([
        f"🟢 {symbol.replace('.JK', '')} — {name}",
        f"• Sektor: {metrics.get('sector') or 'n/a'}",
        f"• Valuasi: PE {_format_multiple(metrics.get('forward_pe'))}",
        f"• Dividen (TTM): {_format_ratio_percent(metrics.get('dividend_yield'))}",
        f"• Laba terakhir: {_format_trillion(metrics.get('latest_earnings'))}",
        f"• Kapitalisasi: {_format_trillion(metrics.get('market_cap'))}",
    ])
