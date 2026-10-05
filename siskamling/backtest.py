"""Backtest point-in-time: apakah skor teknikal menandai saham SEBELUM disuspensi BEI?

Aturan anti look-ahead:
- Untuk hari i, skor hanya memakai bars[: i + 1].
- Bar pada/setelah tanggal suspensi dibuang.
- Ambang skor ditetapkan di konstanta di bawah, bukan dicari dari hasil.
Kontrol: sampel saham yang TIDAK disuspensi pada periode yang sama (untuk false positive rate).
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

from . import sectors
from .score import features, tech_score

THRESHOLD = 40          # skor >= ini dianggap "kentongan"
LOOKBACK_DAYS = 10      # hitung "tertangkap" jika ada alarm di T-10..T-1 (hari bursa)
FETCH_SPAN = 88        # hari kalender per tarikan (batas endpoint 90)
ROOT = Path(__file__).resolve().parent.parent


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def load_bars(symbol: str, end: date) -> list[dict]:
    start = end - timedelta(days=FETCH_SPAN)
    raw = sectors.daily(symbol, start.isoformat(), end.isoformat())
    bars = []
    for b in raw:
        if b.get("close") is not None and b.get("volume") is not None:
            c = dict(b)
            if not c.get("open"):
                c["open"] = c["close"]
            bars.append(c)
    bars.sort(key=lambda b: b["date"])
    return bars


def scan(bars: list[dict], cutoff: date | None) -> list[dict]:
    """Skor tiap hari. Jika cutoff diberikan, hanya bar sebelum cutoff yang dipakai."""
    if cutoff:
        bars = [b for b in bars if _d(b["date"]) < cutoff]
    out = []
    for i in range(20, len(bars)):
        f = features(bars[: i + 1])          # <- tidak ada akses ke bars[i+1:]
        if f is None:
            continue
        sc, why = tech_score(f)
        out.append({"date": bars[i]["date"][:10], "score": sc, "why": why, "ret_1d": f["ret_1d"]})
    return out


def evaluate_suspended(susp: list[dict]) -> list[dict]:
    rows = []
    for x in susp:
        sym, sd = x["symbol"], _d(x["suspension_date"])
        try:
            bars = load_bars(sym, sd)
        except sectors.SectorsError as e:
            rows.append({"symbol": sym, "suspended": str(sd), "error": str(e)[:80]})
            continue
        days = scan(bars, sd)
        if not days:
            rows.append({"symbol": sym, "suspended": str(sd), "error": "bar kurang dari 21"})
            continue
        win = days[-LOOKBACK_DAYS:]
        hit = [d for d in win if d["score"] >= THRESHOLD]
        first = hit[0] if hit else None
        rows.append({
            "symbol": sym, "suspended": str(sd), "n_days": len(days),
            "max_score": max(d["score"] for d in win),
            "caught": bool(hit),
            "lead_days": (sd - _d(first["date"])).days if first else None,
            "reason": (x.get("reason") or "")[:60],
        })
    return rows


def evaluate_controls(symbols: list[str], end: date) -> dict:
    """Berapa persen hari-saham biasa yang memicu alarm (false positive per saham-hari)."""
    total = alarms = 0
    per = []
    for sym in symbols:
        try:
            bars = load_bars(sym, end)
        except sectors.SectorsError:
            continue
        days = scan(bars, None)[-40:]
        a = sum(1 for d in days if d["score"] >= THRESHOLD)
        total += len(days); alarms += a
        per.append({"symbol": sym, "days": len(days), "alarm_days": a})
    return {"stock_days": total, "alarm_days": alarms,
            "fp_rate": (alarms / total) if total else None, "per_symbol": per}


def main(controls_file: str | None = None) -> None:
    susp = json.loads((ROOT / "data" / "suspensions.json").read_text())
    susp = [x for x in susp if "harga" in (x.get("reason") or "").lower()]
    seen, uniq = set(), []
    for x in susp:                       # satu baris per saham (suspensi paling awal)
        if x["symbol"] not in seen:
            seen.add(x["symbol"]); uniq.append(x)
    rows = evaluate_suspended(uniq)
    ok = [r for r in rows if "error" not in r]
    res = {"threshold": THRESHOLD, "lookback_days": LOOKBACK_DAYS,
           "n_suspended": len(uniq), "n_evaluated": len(ok),
           "n_caught": sum(r["caught"] for r in ok), "rows": rows}
    if controls_file:
        syms = json.loads(Path(controls_file).read_text())
        susp_syms = {x["symbol"] for x in uniq}
        syms = [s for s in syms if s not in susp_syms]
        res["controls"] = evaluate_controls(syms, date(2026, 10, 1))
    out = ROOT / "data" / "backtest_result.json"
    out.write_text(json.dumps(res, indent=1, default=str))
    print(f"evaluated={res['n_evaluated']}/{res['n_suspended']} caught={res['n_caught']}")
    if "controls" in res:
        c = res["controls"]
        print(f"controls stock_days={c['stock_days']} alarm_days={c['alarm_days']} fp={c['fp_rate']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
