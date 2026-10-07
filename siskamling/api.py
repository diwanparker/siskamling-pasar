"""HTTP API (FastAPI) untuk Siskamling Pasar.

Membungkus orkestrasi di `siskamling.bot` menjadi endpoint HTTP agar otomasi
(n8n, cron eksternal, dsb.) cukup memanggil endpoint — tanpa subprocess.

Menjalankan:
    uvicorn siskamling.api:app --host 0.0.0.0 --port 8000
    # atau: python3 -m siskamling.bot --serve --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .bot import execute_daily_broadcast, execute_morning_brief, score_ticker

app = FastAPI(title="Siskamling Pasar API", version="0.1.0")


class PatrolRequest(BaseModel):
    """Parameter patroli risiko sore. Semua opsional (jatuh ke default/env)."""

    threshold: int | None = None
    n_gainers: int | None = None
    fetch_days: int | None = None


class MorningBriefRequest(BaseModel):
    """Parameter briefing pagi (screening fundamental). Semua opsional."""

    n_candidates: int | None = None
    max_pe: float | None = None
    min_dividend_yield: float | None = None
    universe_size: int | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/patrol")
def patrol(request: PatrolRequest | None = None) -> dict[str, Any]:
    """Jalankan patroli risiko sore + broadcast, kembalikan run manifest."""
    params = request or PatrolRequest()
    return execute_daily_broadcast(
        threshold=params.threshold,
        n_gainers=params.n_gainers,
        fetch_days=params.fetch_days,
    )


@app.post("/morning-brief")
def morning_brief(request: MorningBriefRequest | None = None) -> dict[str, Any]:
    """Jalankan briefing pagi (screening fundamental) + broadcast, kembalikan manifest."""
    params = request or MorningBriefRequest()
    return execute_morning_brief(
        n_candidates=params.n_candidates,
        max_pe=params.max_pe,
        min_dividend_yield=params.min_dividend_yield,
        universe_size=params.universe_size,
    )


@app.get("/ronda/{ticker}")
def ronda(ticker: str) -> dict[str, Any]:
    """Hitung skor risiko satu saham."""
    result = score_ticker(ticker)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result
