"""Runner Siskamling Pasar: skoring risiko, briefing pagi, broadcast, dan CLI.

Logika platform (Telegram, Discord, ...) didelegasikan sepenuhnya ke paket
`siskamling.platforms`. Modul ini hanya berisi domain (skoring/screening) dan
orkestrasi, sehingga platform baru tidak menambah kode platform-spesifik di sini.

Orkestrasi selalu menghasilkan `messages` (narasi teks polos, lihat
`PlainTextChannel`) di manifest, terlepas dari kanal mana pun. Pengiriman ke
kanal bersifat opsional (`dry_run` / tidak ada kredensial).
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
from .narrator import narrate, narrate_candidate
from .platforms import (
    CommandRouter,
    PlainTextChannel,
    all_channels,
    build_briefing_messages,
    build_report_messages,
    dispatch_briefing,
    dispatch_report,
    run_listeners,
)
from .score import calculate_risk_score, extract_features

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger("siskamling.bot")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIRECTORY = PROJECT_ROOT / "runs"
DEFAULT_FETCH_DAYS = 88
MINIMUM_REQUIRED_BARS = 21
RISK_ALERT_THRESHOLD = 40

# Briefing pagi — screening fundamental deterministik
DEFAULT_N_CANDIDATES = 3
DEFAULT_MAX_PE = 20.0
DEFAULT_MIN_DIVIDEND_YIELD_PCT = 5.0
DEFAULT_UNIVERSE_SIZE = 20

# Perender teks polos untuk manifest/API (tidak pernah dikirim ke kanal)
PLAIN_TEXT_CHANNEL = PlainTextChannel()


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

def _fetch_top_gainers(n_gainers: int) -> list[dict[str, Any]]:
    """Tarik daftar saham top gainers harian dari Sectors API."""
    gainers_response = sectors.get(
        "/v2/companies/top-changes/",
        {
            "classifications": "top_gainers",
            "periods": "1d",
            "n_stock": n_gainers,
            "min_mcap_billion": 0,
        },
        cache=False,
    )
    return gainers_response.get("top_gainers", {}).get("1d", [])


def _evaluate_gainers(
    gainer_items: list[dict[str, Any]],
    threshold: int,
    fetch_days: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Evaluasi setiap saham top gainer dan filter yang melampaui ambang risiko."""
    triggered_alerts: list[dict[str, Any]] = []
    encountered_errors: list[str] = []

    for item in gainer_items:
        symbol = item.get("symbol", "").replace(".JK", "")
        if not symbol:
            continue

        try:
            result = score_ticker(symbol, days=fetch_days)
            if "error" in result:
                encountered_errors.append(f"{symbol}: {result['error']}")
                continue
            if result["score"] >= threshold:
                triggered_alerts.append(result)
        except Exception as error:  # Tangkapan defensif untuk kesalahan tak terduga per saham
            encountered_errors.append(f"{symbol}: {error}")

    return triggered_alerts, encountered_errors


def _save_manifest_to_disk(manifest: dict[str, Any]) -> Path:
    """Tulis run manifest ke disk sebagai bukti otomasi harian."""
    RUNS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    manifest_path = RUNS_DIRECTORY / f"{date.today().isoformat()}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Run manifest berhasil disimpan: %s", manifest_path)
    return manifest_path


def execute_daily_broadcast(
    threshold: int | None = None,
    n_gainers: int | None = None,
    fetch_days: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Pindai top gainers harian, evaluasi risiko, broadcast alert, dan catat manifest.

    Manifest selalu memuat `messages` (narasi teks polos). `dry_run=True` menahan
    pengiriman ke kanal Telegram/Discord.
    """
    resolved_threshold = threshold if threshold is not None else int(os.environ.get("RISK_ALERT_THRESHOLD", RISK_ALERT_THRESHOLD))
    resolved_n_gainers = n_gainers if n_gainers is not None else int(os.environ.get("N_GAINERS", 20))
    resolved_fetch_days = fetch_days if fetch_days is not None else int(os.environ.get("FETCH_DAYS", DEFAULT_FETCH_DAYS))

    logger.info(
        "Memulai patroli ronda broadcast harian (threshold=%d, n_gainers=%d, fetch_days=%d, dry_run=%s)",
        resolved_threshold,
        resolved_n_gainers,
        resolved_fetch_days,
        dry_run,
    )
    start_timestamp = datetime.now(timezone.utc).isoformat()

    try:
        gainer_items = _fetch_top_gainers(resolved_n_gainers)
    except sectors.SectorsError as error:
        logger.error("Gagal mengambil daftar top gainers: %s", error)
        return _build_manifest(start_timestamp, 0, [], [str(error)], messages=[])

    if not gainer_items:
        logger.warning("Tidak ada daftar top gainers untuk hari ini")
        return _build_manifest(
            start_timestamp, 0, [], [],
            messages=build_report_messages(PLAIN_TEXT_CHANNEL, []),
        )

    triggered_alerts, encountered_errors = _evaluate_gainers(
        gainer_items,
        resolved_threshold,
        resolved_fetch_days,
    )

    messages = build_report_messages(PLAIN_TEXT_CHANNEL, triggered_alerts)

    if not dry_run:
        # Fan-out ke seluruh kanal notifikasi yang terkonfigurasi (Telegram, Discord, ...).
        # Tidak ada kanal terkonfigurasi → aman, tidak ada yang dikirim.
        dispatch_report(all_channels(), triggered_alerts)

    run_manifest = _build_manifest(start_timestamp, len(gainer_items), triggered_alerts, encountered_errors, messages=messages)
    RUNS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    manifest_path = RUNS_DIRECTORY / f"{date.today().isoformat()}.json"
    manifest_path.write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")
    logger.info("Run manifest berhasil disimpan: %s", manifest_path)
    return run_manifest


from dataclasses import dataclass


@dataclass(frozen=True)
class ManifestData:
    """Objek data masukan untuk penyusunan run manifest."""

    start_timestamp: str
    n_gainers_scanned: int
    triggered_alerts: list[dict[str, Any]]
    encountered_errors: list[str]


def _build_manifest(
    start_timestamp: str,
    n_gainers_scanned: int,
    triggered_alerts: list[dict[str, Any]],
    encountered_errors: list[str],
    messages: list[str],
) -> dict[str, Any]:
    """Susun run manifest (bukti otomasi terjadwal tanpa intervensi manusia)."""
    if isinstance(start_timestamp, ManifestData):
        start_ts = start_timestamp.start_timestamp
        scanned = start_timestamp.n_gainers_scanned
        alerts = start_timestamp.triggered_alerts
        errors = start_timestamp.encountered_errors
    else:
        start_ts = start_timestamp
        scanned = n_gainers_scanned
        alerts = triggered_alerts or []
        errors = encountered_errors or []

    return {
        "run_id": hashlib.sha1(start_ts.encode()).hexdigest()[:12],
        "started_at": start_ts,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "n_gainers_scanned": n_gainers_scanned,
        "n_alerts": len(triggered_alerts),
        "n_errors": len(encountered_errors),
        "alerts": [{"symbol": alert["symbol"], "score": alert["score"]} for alert in triggered_alerts],
        "messages": messages,
        "errors": encountered_errors[:10],
    }


# ─── Briefing Pagi: Screening Fundamental ──────────────────────────

def _extract_fundamental_metrics(report: dict[str, Any]) -> dict[str, Any]:
    """Ambil metrik fundamental relevan dari payload Company Report."""
    overview = report.get("overview") or {}
    valuation = report.get("valuation") or {}
    dividend = report.get("dividend") or {}
    financials = report.get("financials") or {}

    latest_earnings: float | None = None
    historical = financials.get("historical_financials") or []
    if historical:
        latest_year = max(historical, key=lambda row: str(row.get("year", "")))
        earnings = latest_year.get("earnings")
        latest_earnings = earnings if isinstance(earnings, (int, float)) else None

    return {
        "company_name": report.get("company_name"),
        "sector": overview.get("sector"),
        "market_cap": overview.get("market_cap"),
        "forward_pe": valuation.get("forward_pe"),
        "dividend_yield": dividend.get("yield_ttm"),
        "latest_earnings": latest_earnings,
    }


def _passes_fundamental_screen(metrics: dict[str, Any], max_pe: float, min_dividend_yield: float) -> bool:
    """Saring deterministik: laba positif, PE wajar, dan dividend yield memadai."""
    earnings = metrics.get("latest_earnings")
    pe_ratio = metrics.get("forward_pe")
    dividend_yield = metrics.get("dividend_yield")

    if not isinstance(earnings, (int, float)) or earnings <= 0:
        return False
    if not isinstance(pe_ratio, (int, float)) or pe_ratio <= 0 or pe_ratio > max_pe:
        return False
    if not isinstance(dividend_yield, (int, float)) or dividend_yield < min_dividend_yield:
        return False
    return True


def execute_morning_brief(
    n_candidates: int | None = None,
    max_pe: float | None = None,
    min_dividend_yield: float | None = None,
    universe_size: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Saring kandidat fundamental sehat, broadcast briefing pagi, dan catat manifest.

    Manifest selalu memuat `messages` (narasi teks polos). `dry_run=True` menahan
    pengiriman ke kanal Telegram/Discord.
    """
    resolved_n = n_candidates if n_candidates is not None else int(os.environ.get("N_CANDIDATES", DEFAULT_N_CANDIDATES))
    resolved_max_pe = max_pe if max_pe is not None else float(os.environ.get("MAX_PE", DEFAULT_MAX_PE))
    resolved_min_yield = (
        min_dividend_yield if min_dividend_yield is not None
        else float(os.environ.get("MIN_DIVIDEND_YIELD", DEFAULT_MIN_DIVIDEND_YIELD_PCT))
    )
    resolved_universe = (
        universe_size if universe_size is not None
        else int(os.environ.get("UNIVERSE_SIZE", DEFAULT_UNIVERSE_SIZE))
    )

    logger.info(
        "Memulai briefing pagi (n_candidates=%d, max_pe=%.1f, min_yield=%.1f%%, universe=%d, dry_run=%s)",
        resolved_n,
        resolved_max_pe,
        resolved_min_yield,
        resolved_universe,
        dry_run,
    )
    start_timestamp = datetime.now(timezone.utc).isoformat()

    try:
        universe = sectors.screener(where="market_cap IS NOT NULL", order_by="-market_cap", limit=resolved_universe)
    except sectors.SectorsError as error:
        logger.error("Gagal mengambil universe screener: %s", error)
        return _build_briefing_manifest(start_timestamp, 0, [], [str(error)], messages=[])

    candidates: list[dict[str, Any]] = []
    encountered_errors: list[str] = []
    min_yield_ratio = resolved_min_yield / 100.0

    for item in universe:
        symbol = str(item.get("symbol", ""))
        if not symbol:
            continue
        try:
            report = sectors.company_report(symbol, sections=["overview", "valuation", "dividend", "financials"])
            metrics = _extract_fundamental_metrics(report)
            if not _passes_fundamental_screen(metrics, resolved_max_pe, min_yield_ratio):
                continue
            candidates.append({
                "symbol": symbol,
                **metrics,
                "narration": narrate_candidate(symbol, metrics),
            })
        except Exception as error:  # Defensive catch: satu kandidat gagal tak menggagalkan run
            encountered_errors.append(f"{symbol}: {error}")

    candidates.sort(key=lambda candidate: (-(candidate.get("dividend_yield") or 0), -(candidate.get("market_cap") or 0)))
    selected = candidates[:resolved_n]

    messages = build_briefing_messages(PLAIN_TEXT_CHANNEL, selected)

    if not dry_run:
        # Fan-out ke seluruh kanal notifikasi yang terkonfigurasi (Telegram, Discord, ...).
        dispatch_briefing(all_channels(), selected)

    manifest = _build_briefing_manifest(start_timestamp, len(universe), selected, encountered_errors, messages=messages)
    RUNS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    manifest_path = RUNS_DIRECTORY / f"morning-{date.today().isoformat()}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Briefing manifest berhasil disimpan: %s", manifest_path)
    return manifest


def _build_briefing_manifest(
    start_timestamp: str,
    n_universe_scanned: int,
    candidates: list[dict[str, Any]],
    encountered_errors: list[str],
    messages: list[str],
) -> dict[str, Any]:
    """Susun manifest briefing pagi (audit trail screening fundamental)."""
    return {
        "run_id": hashlib.sha1(f"morning-{start_timestamp}".encode()).hexdigest()[:12],
        "started_at": start_timestamp,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "n_universe_scanned": n_universe_scanned,
        "n_candidates": len(candidates),
        "n_errors": len(encountered_errors),
        "candidates": [
            {
                "symbol": candidate["symbol"],
                "sector": candidate.get("sector"),
                "forward_pe": candidate.get("forward_pe"),
                "dividend_yield": candidate.get("dividend_yield"),
                "market_cap": candidate.get("market_cap"),
            }
            for candidate in candidates
        ],
        "messages": messages,
        "errors": encountered_errors[:10],
    }


# ─── HTTP API (FastAPI) ────────────────────────────────────────────

def _run_api(host: str, port: int) -> None:
    """Jalankan server HTTP. Import uvicorn ditunda agar CLI tetap jalan tanpa dependensi."""
    try:
        import uvicorn
    except ImportError as error:
        raise SystemExit("uvicorn belum terpasang. Jalankan: pip install -r requirements.txt") from error

    logger.info("Menjalankan HTTP API di http://%s:%d", host, port)
    uvicorn.run("siskamling.api:app", host=host, port=port)


# ─── CLI Entrypoint ────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Bot & Runner Siskamling Pasar")
    parser.add_argument("--broadcast", action="store_true", help="Jalankan siklus patroli dan broadcast harian")
    parser.add_argument("--morning-brief", action="store_true", dest="morning_brief", help="Jalankan briefing pagi (screening fundamental) dan broadcast")
    parser.add_argument("--poll", action="store_true", help="Jalankan listener bot Telegram & Discord dalam mode polling")
    parser.add_argument("--serve", action="store_true", help="Jalankan HTTP API (FastAPI + uvicorn)")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run", help="Jangan kirim ke kanal; cukup kembalikan narasi")
    parser.add_argument("--test", metavar="TICKER", help="Uji kalkulasi dan narasi satu ticker di konsol")
    parser.add_argument("--threshold", type=int, default=None, help="Ambang skor risiko untuk alert (default: 40)")
    parser.add_argument("--n-gainers", type=int, default=None, dest="n_gainers", help="Jumlah saham top gainers yang dipindai (default: 20)")
    parser.add_argument("--days", type=int, default=None, dest="days", help="Jumlah hari bar OHLCV harian yang diambil (default: 88)")
    parser.add_argument("--top", type=int, default=None, help="Jumlah kandidat briefing pagi (default: 3)")
    parser.add_argument("--max-pe", type=float, default=None, dest="max_pe", help="Batas PE briefing pagi (default: 20)")
    parser.add_argument("--min-dividend-yield", type=float, default=None, dest="min_dividend_yield", help="Dividend yield minimum briefing pagi dalam %% (default: 5)")
    parser.add_argument("--universe-size", type=int, default=None, dest="universe_size", help="Jumlah saham universe yang diperiksa briefing pagi (default: 20)")
    parser.add_argument("--host", default="127.0.0.1", help="Host HTTP API (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port HTTP API (default: 8000)")
    parser.add_argument("--json", action="store_true", help="Cetak run manifest dalam format JSON ke stdout (untuk n8n/otomasi)")
    args = parser.parse_args()

    if args.serve:
        _run_api(args.host, args.port)
    elif args.broadcast:
        manifest = execute_daily_broadcast(
            threshold=args.threshold,
            n_gainers=args.n_gainers,
            fetch_days=args.days,
            dry_run=args.dry_run,
        )
        if args.json:
            print(json.dumps(manifest, indent=2, ensure_ascii=False, default=str))
    elif args.morning_brief:
        manifest = execute_morning_brief(
            n_candidates=args.top,
            max_pe=args.max_pe,
            min_dividend_yield=args.min_dividend_yield,
            universe_size=args.universe_size,
            dry_run=args.dry_run,
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
