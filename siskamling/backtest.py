"""Backtest point-in-time: Pengujian skor teknikal anti-pom-pom terhadap data historis suspensi BEI.

Aturan Anti Look-Ahead:
- Pada hari evaluasi `t`, kalkulasi hanya menggunakan baris data `bars[:t+1]`.
- Bar data pada atau setelah tanggal suspensi diabaikan.
- Ambang skor (threshold) ditetapkan di awal (ex-ante), bukan hasil fitting data.
- Dilengkapi kelompok kontrol (saham blue chip) untuk mengukur False Positive Rate.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from . import sectors
from .score import calculate_risk_score, extract_features

logger = logging.getLogger(__name__)

SCORE_THRESHOLD = 40
EVALUATION_LOOKBACK_DAYS = 10
FETCH_SPAN_DAYS = 88
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_date(date_str: str) -> date:
    """Konversi string ISO date (YYYY-MM-DD) menjadi objek date."""
    return date.fromisoformat(date_str[:10])


def load_daily_bars(symbol: str, end_date: date) -> list[dict[str, Any]]:
    """Tarik baris data harian yang sudah ternormalisasi hingga end_date."""
    start_date = end_date - timedelta(days=FETCH_SPAN_DAYS)
    return sectors.daily(symbol, start_date.isoformat(), end_date.isoformat(), clean=True)


def scan_historical_bars(bars: list[dict[str, Any]], cutoff_date: date | None = None) -> list[dict[str, Any]]:
    """Kalkulasi skor harian secara point-in-time.

    Data dipotong ketat sebelum cutoff_date jika ditentukan.
    """
    if cutoff_date:
        bars = [b for b in bars if parse_date(str(b["date"])) < cutoff_date]

    daily_scores: list[dict[str, Any]] = []
    for index in range(20, len(bars)):
        window = bars[: index + 1]  # Strict point-in-time slice
        features = extract_features(window)
        if features is None:
            continue
        score, reasons = calculate_risk_score(features)
        daily_scores.append({
            "date": str(bars[index]["date"])[:10],
            "score": score,
            "reasons": reasons,
            "return_1d": features["return_1d"],
        })
    return daily_scores


def evaluate_suspended_stocks(suspensions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evaluasi apakah saham yang disuspensi BEI berhasil dideteksi sebelum tanggal suspensi."""
    evaluation_rows: list[dict[str, Any]] = []

    for item in suspensions:
        symbol = str(item["symbol"])
        suspension_date = parse_date(str(item["suspension_date"]))

        try:
            bars = load_daily_bars(symbol, suspension_date)
        except sectors.SectorsError as err:
            evaluation_rows.append({"symbol": symbol, "suspended": str(suspension_date), "error": str(err)[:80]})
            continue

        historical_scans = scan_historical_bars(bars, cutoff_date=suspension_date)
        if not historical_scans:
            evaluation_rows.append({
                "symbol": symbol,
                "suspended": str(suspension_date),
                "error": "Jumlah baris data kurang dari batas minimum",
            })
            continue

        evaluation_window = historical_scans[-EVALUATION_LOOKBACK_DAYS:]
        alert_days = [day for day in evaluation_window if day["score"] >= SCORE_THRESHOLD]
        first_alert = alert_days[0] if alert_days else None

        lead_days = (suspension_date - parse_date(first_alert["date"])).days if first_alert else None
        max_score = max(day["score"] for day in evaluation_window)

        evaluation_rows.append({
            "symbol": symbol,
            "suspended": str(suspension_date),
            "n_days": len(historical_scans),
            "max_score": max_score,
            "caught": bool(alert_days),
            "lead_days": lead_days,
            "reason": str(item.get("reason", ""))[:60],
        })

    return evaluation_rows


def evaluate_control_stocks(symbols: list[str], end_date: date) -> dict[str, Any]:
    """Evaluasi kelompok kontrol untuk menghitung False Positive Rate."""
    total_stock_days = 0
    total_alarm_days = 0
    per_symbol_breakdown: list[dict[str, Any]] = []

    for symbol in symbols:
        try:
            bars = load_daily_bars(symbol, end_date)
        except sectors.SectorsError:
            continue

        recent_days = scan_historical_bars(bars)[-40:]
        alarm_count = sum(1 for day in recent_days if day["score"] >= SCORE_THRESHOLD)

        total_stock_days += len(recent_days)
        total_alarm_days += alarm_count
        per_symbol_breakdown.append({
            "symbol": symbol,
            "days": len(recent_days),
            "alarm_days": alarm_count,
        })

    fp_rate = (total_alarm_days / total_stock_days) if total_stock_days else 0.0
    return {
        "stock_days": total_stock_days,
        "alarm_days": total_alarm_days,
        "fp_rate": fp_rate,
        "per_symbol": per_symbol_breakdown,
    }


def _load_unique_price_suspensions(suspensions_file: Path) -> list[dict[str, Any]]:
    """Muat dan filter data suspensi terkait lonjakan harga kumulatif tanpa duplikasi."""
    suspensions_data: list[dict[str, Any]] = json.loads(suspensions_file.read_text(encoding="utf-8"))
    seen_symbols: set[str] = set()
    unique_suspensions: list[dict[str, Any]] = []

    for item in suspensions_data:
        is_price_related = "harga" in str(item.get("reason", "")).lower()
        symbol = str(item.get("symbol", ""))
        if is_price_related and symbol and symbol not in seen_symbols:
            seen_symbols.add(symbol)
            unique_suspensions.append(item)

    return unique_suspensions


def _create_evaluation_summary(
    unique_suspensions: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Susun ringkasan metrik deteksi dari hasil evaluasi suspensi."""
    valid_evaluations = [row for row in evaluation_rows if "error" not in row]
    return {
        "threshold": SCORE_THRESHOLD,
        "lookback_days": EVALUATION_LOOKBACK_DAYS,
        "n_suspended": len(unique_suspensions),
        "n_evaluated": len(valid_evaluations),
        "n_caught": sum(1 for row in valid_evaluations if row.get("caught")),
        "rows": evaluation_rows,
    }


def run_backtest(controls_path: str | None = None) -> dict[str, Any]:
    """Jalankan siklus backtest lengkap dan simpan hasilnya ke data/backtest_result.json."""
    suspensions_file = PROJECT_ROOT / "data" / "suspensions.json"
    unique_suspensions = _load_unique_price_suspensions(suspensions_file)

    evaluation_rows = evaluate_suspended_stocks(unique_suspensions)
    summary = _create_evaluation_summary(unique_suspensions, evaluation_rows)

    if controls_path:
        controls_file = Path(controls_path)
        control_symbols: list[str] = json.loads(controls_file.read_text(encoding="utf-8"))
        seen_symbols = {str(item["symbol"]) for item in unique_suspensions}
        filtered_controls = [s for s in control_symbols if s not in seen_symbols]
        summary["controls"] = evaluate_control_stocks(filtered_controls, date(2026, 10, 1))

    output_file = PROJECT_ROOT / "data" / "backtest_result.json"
    output_file.write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")

    print(f"evaluated={summary['n_evaluated']}/{summary['n_suspended']} caught={summary['n_caught']}")
    if "controls" in summary:
        ctrl = summary["controls"]
        print(f"controls stock_days={ctrl['stock_days']} alarm_days={ctrl['alarm_days']} fp={ctrl['fp_rate']}")

    return summary


def main() -> None:
    controls_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run_backtest(controls_arg)


if __name__ == "__main__":
    main()
