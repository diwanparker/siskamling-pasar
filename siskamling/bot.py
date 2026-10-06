"""Bot Telegram Siskamling Pasar & Runner Broadcast.

Fitur:
- `/ronda TICKER` — Pemeriksaan interaktif risiko satu saham.
- `/start`, `/help` — Panduan penggunaan bot.
- `--broadcast` — Eksekusi patroli harian (cron) + penyimpanan run manifest.
- `--test TICKER` — Pengujian mandiri tanpa Telegram.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import sectors
from .narrator import narrate
from .score import calculate_risk_score, extract_features

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger("siskamling.bot")

TELEGRAM_API_BASE = "https://api.telegram.org/bot"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIRECTORY = PROJECT_ROOT / "runs"
DEFAULT_FETCH_DAYS = 88
MINIMUM_REQUIRED_BARS = 21
RISK_ALERT_THRESHOLD = 40


def get_telegram_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def get_telegram_chat_id() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", "").strip()


# ─── Telegram API Client ───────────────────────────────────────────

def send_telegram_request(method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Kirim request POST ke Telegram Bot API."""
    token = get_telegram_token()
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN belum dikonfigurasi")
        return None

    url = f"{TELEGRAM_API_BASE}{token}/{method}"
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        logger.error("Telegram API error %s: %s", error.code, error.read()[:200])
        return None
    except urllib.error.URLError as error:
        logger.error("Koneksi Telegram gagal: %s", error)
        return None


def send_message(chat_id: str, text: str, parse_mode: str = "Markdown") -> dict[str, Any] | None:
    """Kirim pesan teks ke chat Telegram."""
    return send_telegram_request("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    })


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


def dispatch_telegram_alerts(triggered_alerts: list[dict[str, Any]], chat_id: str | None = None) -> None:
    """Kirim hasil evaluasi ronda ke kanal atau grup Telegram (Decoupled Notification Sink)."""
    target_chat_id = chat_id or get_telegram_chat_id()
    if not target_chat_id:
        return

    if not triggered_alerts:
        safe_message = (
            "🛡️ *Laporan Ronda Sore*\n\n"
            "Situasi pasar terpantau kondusif. Tidak ada saham mencurigakan pada jajaran top gainers hari ini."
        )
        send_message(target_chat_id, safe_message)
        return

    header_message = (
        f"🔔 *Laporan Ronda Sore — {date.today().isoformat()}*\n\n"
        f"Perhatian warga, terdeteksi *{len(triggered_alerts)} saham* masuk radar risiko:\n"
    )
    send_message(target_chat_id, header_message)
    for alert in sorted(triggered_alerts, key=lambda a: -a["score"]):
        send_message(target_chat_id, alert["narration"])
        time.sleep(1)  # Hindari Telegram API rate limit


# ─── Handler Perintah Interaktif ───────────────────────────────────

def handle_ronda_command(chat_id: str, message_text: str) -> None:
    """Proses perintah /ronda TICKER."""
    tokens = message_text.strip().split()
    if len(tokens) < 2:
        send_message(chat_id, "ℹ️ Format perintah: `/ronda TICKER` (contoh: `/ronda BBCA` atau `/ronda UNSP`)")
        return

    ticker = tokens[1].upper()
    send_message(chat_id, f"⏳ Sedang patroli ke pos saham *{ticker}*...")
    evaluation = score_ticker(ticker)

    if "error" in evaluation:
        send_message(chat_id, f"❌ *{ticker}*: {evaluation['error']}")
        return

    send_message(chat_id, evaluation["narration"])


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
    chat_id = get_telegram_chat_id()

    try:
        gainers_response = sectors.get("/v2/companies/top-changes/", {
            "classifications": "top_gainers",
            "periods": "1d",
            "n_stock": resolved_n_gainers,
            "min_mcap_billion": 0,
        }, cache=False)
    except sectors.SectorsError as error:
        logger.error("Gagal mengambil daftar top gainers: %s", error)
        run_manifest = {
            "run_id": hashlib.sha1(start_timestamp.encode()).hexdigest()[:12],
            "started_at": start_timestamp,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "n_gainers_scanned": 0,
            "n_alerts": 0,
            "n_errors": 1,
            "alerts": [],
            "errors": [str(error)],
        }
        return run_manifest

    gainer_items = gainers_response.get("top_gainers", {}).get("1d", [])
    if not gainer_items:
        logger.warning("Tidak ada daftar top gainers untuk hari ini")
        run_manifest = {
            "run_id": hashlib.sha1(start_timestamp.encode()).hexdigest()[:12],
            "started_at": start_timestamp,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "n_gainers_scanned": 0,
            "n_alerts": 0,
            "n_errors": 0,
            "alerts": [],
            "errors": [],
        }
        return run_manifest

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

    # Kirim hasil ronda ke kanal/grup Telegram jika chat_id tersedia (Decoupled sink)
    dispatch_telegram_alerts(triggered_alerts, chat_id=chat_id)

    # Simpan Run Manifest (Bukti otomasi terjadwal tanpa intervensi manusia)
    run_manifest = {
        "run_id": hashlib.sha1(start_timestamp.encode()).hexdigest()[:12],
        "started_at": start_timestamp,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "n_gainers_scanned": len(gainer_items),
        "n_alerts": len(triggered_alerts),
        "n_errors": len(encountered_errors),
        "alerts": [{"symbol": a["symbol"], "score": a["score"]} for a in triggered_alerts],
        "errors": encountered_errors[:10],
    }
    RUNS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    manifest_path = RUNS_DIRECTORY / f"{date.today().isoformat()}.json"
    manifest_path.write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")
    logger.info("Run manifest berhasil disimpan: %s", manifest_path)
    return run_manifest


# ─── Long Polling Loop ─────────────────────────────────────────────

def run_polling_loop() -> None:
    """Jalankan long-polling daemon untuk merespons pesan Telegram secara live."""
    token = get_telegram_token()
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN wajib diisi untuk menjalankan polling")
        sys.exit(1)

    logger.info("Bot Siskamling Pasar siap berpatroli (polling mode aktif)...")
    last_update_id = 0

    while True:
        try:
            updates = send_telegram_request("getUpdates", {"offset": last_update_id, "timeout": 30})
            if not updates or not updates.get("ok"):
                time.sleep(5)
                continue

            for update in updates.get("result", []):
                last_update_id = update["update_id"] + 1
                message = update.get("message", {})
                message_text = str(message.get("text", ""))
                chat_id = str(message.get("chat", {}).get("id", ""))

                if not chat_id or not message_text:
                    continue

                if message_text.startswith("/ronda"):
                    handle_ronda_command(chat_id, message_text)
                elif message_text.startswith("/start") or message_text.startswith("/help"):
                    welcome_text = (
                        "🏘️ *Siskamling Pasar*\n\n"
                        "Pos ronda otomatis untuk mendeteksi saham berisiko pom-pom di IDX.\n\n"
                        "• `/ronda TICKER` — Periksa skor risiko suatu saham (contoh: `/ronda BBCA`)\n"
                        "• Patroli sore otomatis setiap hari bursa jam 16:30 WIB.\n\n"
                        "⚠️ *Bukan saran investasi.* Data publik bersumber dari Sectors.app."
                    )
                    send_message(chat_id, welcome_text)

        except KeyboardInterrupt:
            logger.info("Polling dihentikan oleh pengguna")
            break
        except Exception as err:
            logger.error("Kesalahan pada polling loop: %s", err)
            time.sleep(5)


# ─── CLI Entrypoint ────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Bot & Runner Siskamling Pasar")
    parser.add_argument("--broadcast", action="store_true", help="Jalankan siklus patroli dan broadcast harian")
    parser.add_argument("--poll", action="store_true", help="Jalankan listener Telegram dalam mode polling")
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
        run_polling_loop()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
