"""Runner Siskamling Pasar: skoring risiko, broadcast, dan CLI.

Logika platform (Telegram, Discord, ...) didelegasikan sepenuhnya ke paket
`siskamling.platforms`. Modul ini hanya berisi domain (skoring) dan orkestrasi,
sehingga platform baru tidak menambah kode platform-spesifik di sini.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import sectors
from .narrator import narrate
from .platforms import CommandRouter, all_channels, dispatch_report, run_listeners
from .score import calculate_risk_score, extract_features

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger("siskamling.bot")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIRECTORY = PROJECT_ROOT / "runs"
DEFAULT_FETCH_DAYS = 88
MINIMUM_REQUIRED_BARS = 21
RISK_ALERT_THRESHOLD = 40


# ─── Penilaian Saham Tunggal ───────────────────────────────────────

def score_ticker(symbol: str, days: int = DEFAULT_FETCH_DAYS) -> dict[str, Any]:
    """Tarik data dan hitung skor risiko teknikal suatu saham."""
    clean_symbol = symbol.upper().replace(".JK", "")
    full_symbol = f"{clean_symbol}.JK"
    today = date.today()
    start_date = today - timedelta(days=days)

    try:
        bars = sectors.daily(clean_symbol, start_date.isoformat(), today.isoformat(), clean=True)
    except sectors.SectorsError as error:
        return {"symbol": full_symbol, "error": f"Gagal mengambil data dari Sectors: {error}"}

    if len(bars) < MINIMUM_REQUIRED_BARS:
        return {"symbol": full_symbol, "error": f"Data harian kurang dari {MINIMUM_REQUIRED_BARS} bar"}

    features = extract_features(bars)
    if features is None:
        return {"symbol": full_symbol, "error": "Gagal menghitung fitur teknikal"}

    score, reasons = calculate_risk_score(features)
    narration = narrate(full_symbol, score, reasons, features)

    return {
        "symbol": full_symbol,
        "score": score,
        "reasons": reasons,
        "features": features,
        "narration": narration,
    }


# ─── Patroli Harian & Run Manifest ─────────────────────────────────

def execute_daily_broadcast(
    threshold: int | None = None,
    n_gainers: int | None = None,
    fetch_days: int | None = None,
) -> dict[str, Any]:
    """Pindai top gainers harian, evaluasi risiko, broadcast alert, dan catat manifest."""
    resolved_threshold = threshold if threshold is not None else int(os.environ.get("RISK_ALERT_THRESHOLD", RISK_ALERT_THRESHOLD))
    resolved_n_gainers = n_gainers if n_gainers is not None else int(os.environ.get("N_GAINERS", 20))
    resolved_fetch_days = fetch_days if fetch_days is not None else int(os.environ.get("FETCH_DAYS", DEFAULT_FETCH_DAYS))

    logger.info(
        "Memulai patroli ronda broadcast harian (threshold=%d, n_gainers=%d, fetch_days=%d)",
        resolved_threshold,
        resolved_n_gainers,
        resolved_fetch_days,
    )
    start_timestamp = datetime.now(timezone.utc).isoformat()

    try:
        gainers_response = sectors.get("/v2/companies/top-changes/", {
            "classifications": "top_gainers",
            "periods": "1d",
            "n_stock": resolved_n_gainers,
            "min_mcap_billion": 0,
        }, cache=False)
    except sectors.SectorsError as error:
        logger.error("Gagal mengambil daftar top gainers: %s", error)
        return _build_manifest(start_timestamp, 0, [], [str(error)])

    gainer_items = gainers_response.get("top_gainers", {}).get("1d", [])
    if not gainer_items:
        logger.warning("Tidak ada daftar top gainers untuk hari ini")
        return _build_manifest(start_timestamp, 0, [], [])

    triggered_alerts: list[dict[str, Any]] = []
    encountered_errors: list[str] = []

    for item in gainer_items:
        symbol = item.get("symbol", "").replace(".JK", "")
        if not symbol:
            continue

        try:
            result = score_ticker(symbol, days=resolved_fetch_days)
            if "error" in result:
                encountered_errors.append(f"{symbol}: {result['error']}")
                continue
            if result["score"] >= resolved_threshold:
                triggered_alerts.append(result)
        except Exception as error:  # Defensive catch for unexpected item failure
            encountered_errors.append(f"{symbol}: {error}")

    # Fan-out ke seluruh kanal notifikasi yang terkonfigurasi (Telegram, Discord, ...)
    dispatch_report(all_channels(), triggered_alerts)

    run_manifest = _build_manifest(start_timestamp, len(gainer_items), triggered_alerts, encountered_errors)
    RUNS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    manifest_path = RUNS_DIRECTORY / f"{date.today().isoformat()}.json"
    manifest_path.write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")
    logger.info("Run manifest berhasil disimpan: %s", manifest_path)
    return run_manifest


def _build_manifest(
    start_timestamp: str,
    n_gainers_scanned: int,
    triggered_alerts: list[dict[str, Any]],
    encountered_errors: list[str],
) -> dict[str, Any]:
    """Susun run manifest (bukti otomasi terjadwal tanpa intervensi manusia)."""
    return {
        "run_id": hashlib.sha1(start_timestamp.encode()).hexdigest()[:12],
        "started_at": start_timestamp,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "n_gainers_scanned": n_gainers_scanned,
        "n_alerts": len(triggered_alerts),
        "n_errors": len(encountered_errors),
        "alerts": [{"symbol": alert["symbol"], "score": alert["score"]} for alert in triggered_alerts],
        "errors": encountered_errors[:10],
    }


# ─── CLI Entrypoint ────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Bot & Runner Siskamling Pasar")
    parser.add_argument("--broadcast", action="store_true", help="Jalankan siklus patroli dan broadcast harian")
    parser.add_argument("--poll", action="store_true", help="Jalankan listener bot Telegram & Discord dalam mode polling")
    parser.add_argument("--test", metavar="TICKER", help="Uji kalkulasi dan narasi satu ticker di konsol")
    parser.add_argument("--threshold", type=int, default=None, help="Ambang skor risiko untuk alert (default: 40)")
    parser.add_argument("--n-gainers", type=int, default=None, dest="n_gainers", help="Jumlah saham top gainers yang dipindai (default: 20)")
    parser.add_argument("--days", type=int, default=None, dest="days", help="Jumlah hari bar OHLCV harian yang diambil (default: 88)")
    parser.add_argument("--json", action="store_true", help="Cetak run manifest dalam format JSON ke stdout (untuk n8n/otomasi)")
    args = parser.parse_args()

    if args.broadcast:
        manifest = execute_daily_broadcast(
            threshold=args.threshold,
            n_gainers=args.n_gainers,
            fetch_days=args.days,
        )
        if args.json:
            print(json.dumps(manifest, indent=2, ensure_ascii=False, default=str))
    elif args.test:
        result = score_ticker(args.test, days=args.days or DEFAULT_FETCH_DAYS)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    elif args.poll:
        router = CommandRouter(evaluate=score_ticker)
        try:
            run_listeners(all_channels(), router)
        except RuntimeError as error:
            logger.error("%s", error)
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
