"""HTTP API (FastAPI) untuk Siskamling Pasar.

Membungkus orkestrasi di `siskamling.bot` menjadi endpoint HTTP agar otomasi
(n8n, cron eksternal, dsb.) cukup memanggil endpoint — tanpa subprocess.

Endpoint tidak terikat pada Telegram/Discord: setiap respons selalu menyertakan
`messages` (narasi teks polos) sehingga bisa di-curl tanpa kredensial kanal.
Set `dry_run: true` untuk memastikan tidak ada pesan yang dikirim ke kanal.

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
    dry_run: bool = False  # True = jangan kirim ke kanal, cukup kembalikan narasi


class MorningBriefRequest(BaseModel):
    """Parameter briefing pagi (screening fundamental). Semua opsional."""

    n_candidates: int | None = None
    max_pe: float | None = None
    min_dividend_yield: float | None = None
    universe_size: int | None = None
    dry_run: bool = False  # True = jangan kirim ke kanal, cukup kembalikan narasi


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/patrol")
def patrol(request: PatrolRequest | None = None) -> dict[str, Any]:
    """Jalankan patroli risiko sore. Respons memuat run manifest + `messages` (narasi)."""
    params = request or PatrolRequest()
    return execute_daily_broadcast(
        threshold=params.threshold,
        n_gainers=params.n_gainers,
        fetch_days=params.fetch_days,
        dry_run=params.dry_run,
    )


@app.post("/morning-brief")
def morning_brief(request: MorningBriefRequest | None = None) -> dict[str, Any]:
    """Jalankan briefing pagi (screening fundamental). Respons memuat manifest + `messages`."""
    params = request or MorningBriefRequest()
    return execute_morning_brief(
        n_candidates=params.n_candidates,
        max_pe=params.max_pe,
        min_dividend_yield=params.min_dividend_yield,
        universe_size=params.universe_size,
        dry_run=params.dry_run,
    )


@app.get("/ronda/{ticker}")
def ronda(ticker: str) -> dict[str, Any]:
    """Hitung skor risiko satu saham (memuat `narration` di respons)."""
    result = score_ticker(ticker)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


class PortfolioUpdateRequest(BaseModel):
    tickers: list[str]


@app.get("/portfolio/{user_id}")
def get_user_portfolio_endpoint(user_id: str) -> dict[str, Any]:
    """Ambil daftar saham portofolio milik user."""
    from .portfolio import get_portfolio
    return {"user_id": user_id, "tickers": get_portfolio(user_id)}


@app.post("/portfolio/{user_id}")
def update_user_portfolio_endpoint(user_id: str, request: PortfolioUpdateRequest) -> dict[str, Any]:
    """Perbarui daftar saham portofolio user."""
    from .portfolio import set_portfolio
    updated = set_portfolio(user_id, request.tickers)
    return {"user_id": user_id, "tickers": updated}


@app.get("/portfolio")
def list_all_portfolios_endpoint() -> dict[str, Any]:
    """Ringkasan seluruh portofolio pengguna yang terdaftar."""
    from .portfolio import get_all_portfolios
    data = get_all_portfolios()
    unique = sorted({t for tickers in data.values() for t in tickers})
    return {"total_users": len(data), "unique_stocks_count": len(unique), "stocks": unique}

