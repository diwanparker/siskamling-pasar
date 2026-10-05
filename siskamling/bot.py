"""Bot Telegram Siskamling Pasar.

Fitur:
- /ronda TICKER — cek skor satu saham secara interaktif
- /start, /help — pengantar
- Broadcast harian — dipanggil dari cron via `python -m siskamling.bot --broadcast`
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from . import sectors
from .narrator import narrate
from .score import features, tech_score

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("siskamling")

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")  # chat/channel untuk broadcast
BASE_TG = "https://api.telegram.org/bot"
ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"

# ─── Telegram helpers ───────────────────────────────────────────────

def tg_request(method: str, data: dict) -> dict | None:
    if not TG_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN belum di-set"); return None
    url = f"{BASE_TG}{TG_TOKEN}/{method}"
    payload = json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        log.error("TG %s: %s %s", method, e.code, e.read()[:200])
        return None


def tg_send(chat_id: str, text: str, parse_mode: str = "Markdown") -> dict | None:
    return tg_request("sendMessage", {
        "chat_id": chat_id, "text": text, "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    })


# ─── Skor satu saham ────────────────────────────────────────────────

def score_ticker(symbol: str) -> dict:
    """Ambil data, hitung skor, return dict lengkap."""
    sym = symbol.upper().replace(".JK", "") + ".JK"
    today = date.today()
    bars = sectors.daily(sym.replace(".JK", ""), (today - timedelta(days=88)).isoformat(), today.isoformat())
    bars = [b for b in bars if b.get("close") and b.get("open") and b.get("volume")]
    bars.sort(key=lambda b: b["date"])
    if len(bars) < 21:
        return {"symbol": sym, "error": "Data harian kurang dari 21 bar"}
    feat = features(bars)
    if feat is None:
        return {"symbol": sym, "error": "Gagal hitung fitur"}
    sc, why = tech_score(feat)
    narration = narrate(sym, sc, why, feat)
    return {"symbol": sym, "score": sc, "why": why, "features": feat, "narration": narration}


# ─── /ronda handler ─────────────────────────────────────────────────

def handle_ronda(chat_id: str, text: str):
    parts = text.strip().split()
    if len(parts) < 2:
        tg_send(chat_id, "Pakai: `/ronda BBCA` atau `/ronda UNSP`")
        return
    ticker = parts[1].upper()
    tg_send(chat_id, f"⏳ Lagi patroli {ticker}...")
    result = score_ticker(ticker)
    if "error" in result:
        tg_send(chat_id, f"❌ {ticker}: {result['error']}")
        return
    tg_send(chat_id, result["narration"])


# ─── Broadcast harian ───────────────────────────────────────────────

def daily_broadcast():
    """Scan top gainers, hitung skor, kirim yang >= 40 ke channel."""
    import hashlib
    from datetime import datetime, timezone

    log.info("Mulai broadcast harian")
    started = datetime.now(timezone.utc).isoformat()

    # Ambil top gainers hari ini
    try:
        gainers = sectors.get("/v2/companies/top-changes/", {
            "classifications": "top_gainers", "periods": "1d",
            "n_stock": 20, "min_mcap_billion": 0,
        }, cache=False)
    except sectors.SectorsError as e:
        log.error("Gagal ambil top gainers: %s", e)
        return

    gainer_list = gainers.get("top_gainers", {}).get("1d", [])
    if not gainer_list:
        log.warning("Tidak ada top gainers hari ini")
        return

    alerts = []
    errors = []
    for g in gainer_list:
        sym = g.get("symbol", "").replace(".JK", "")
        if not sym:
            continue
        try:
            r = score_ticker(sym)
            if "error" in r:
                errors.append(f"{sym}: {r['error']}")
                continue
            if r["score"] >= 40:
                alerts.append(r)
        except Exception as e:
            errors.append(f"{sym}: {e}")

    # Kirim ke channel
    if not alerts:
        msg = "🛡️ *Laporan Ronda Sore*\n\nHari ini aman, tidak ada saham mencurigakan dari top gainers."
        tg_send(TG_CHAT, msg)
    else:
        header = f"🔔 *Laporan Ronda Sore — {date.today().isoformat()}*\n\n{len(alerts)} saham masuk radar:\n"
        tg_send(TG_CHAT, header)
        for a in sorted(alerts, key=lambda x: -x["score"]):
            tg_send(TG_CHAT, a["narration"])
            time.sleep(1)  # rate limit

    # Run manifest
    manifest = {
        "run_id": hashlib.sha1(started.encode()).hexdigest()[:12],
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "n_gainers_scanned": len(gainer_list),
        "n_alerts": len(alerts),
        "n_errors": len(errors),
        "alerts": [{"symbol": a["symbol"], "score": a["score"]} for a in alerts],
        "errors": errors[:10],
    }
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    mpath = RUNS_DIR / f"{date.today().isoformat()}.json"
    mpath.write_text(json.dumps(manifest, indent=1))
    log.info("Manifest: %s", mpath)


# ─── Polling loop ───────────────────────────────────────────────────

def poll():
    """Long-polling bot Telegram sederhana."""
    if not TG_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN harus di-set")
        sys.exit(1)
    log.info("Bot mulai polling...")
    offset = 0
    while True:
        try:
            r = tg_request("getUpdates", {"offset": offset, "timeout": 30})
            if not r or not r.get("ok"):
                time.sleep(5); continue
            for upd in r.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message", {})
                text = msg.get("text", "")
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if not chat_id:
                    continue
                if text.startswith("/ronda"):
                    handle_ronda(chat_id, text)
                elif text.startswith("/start") or text.startswith("/help"):
                    tg_send(chat_id, (
                        "🏘️ *Siskamling Pasar*\n\n"
                        "Bot pemantau saham mencurigakan di IDX.\n\n"
                        "• `/ronda BBCA` — cek skor satu saham\n"
                        "• Broadcast otomatis tiap hari bursa sore\n\n"
                        "⚠️ Bukan saran investasi. Data dari Sectors.app."
                    ))
        except KeyboardInterrupt:
            log.info("Bot berhenti"); break
        except Exception as e:
            log.error("Poll error: %s", e)
            time.sleep(5)


# ─── CLI ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Siskamling Pasar Bot")
    parser.add_argument("--broadcast", action="store_true", help="Jalankan broadcast harian")
    parser.add_argument("--poll", action="store_true", help="Jalankan polling bot")
    parser.add_argument("--test", metavar="TICKER", help="Tes skor satu saham (tanpa Telegram)")
    args = parser.parse_args()

    if args.broadcast:
        daily_broadcast()
    elif args.test:
        r = score_ticker(args.test)
        print(json.dumps(r, indent=1, ensure_ascii=False, default=str))
    elif args.poll:
        poll()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
