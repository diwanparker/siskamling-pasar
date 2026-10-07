"""Modul manajemen portofolio dan watchlist saham warga (personal asset tracking)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PORTFOLIO_FILE = Path(__file__).resolve().parent.parent / "data" / "portofolio.json"


def clean_ticker(ticker: str) -> str:
    """Normalisasi kode ticker IDX menjadi format TICKER.JK."""
    cleaned = ticker.strip().upper().rstrip(",.;:")
    if not cleaned:
        return ""
    if cleaned.endswith(".JK"):
        return cleaned
    return f"{cleaned}.JK"


def _load_data() -> dict[str, list[str]]:
    if not PORTFOLIO_FILE.exists():
        return {}
    try:
        content = PORTFOLIO_FILE.read_text(encoding="utf-8")
        if not content.strip():
            return {}
        return json.loads(content)
    except (OSError, json.JSONDecodeError) as error:
        logger.error("Gagal membaca data portofolio: %s", error)
        return {}


def _save_data(data: dict[str, list[str]]) -> None:
    PORTFOLIO_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        PORTFOLIO_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as error:
        logger.error("Gagal menyimpan data portofolio: %s", error)


def get_portfolio(user_id: str) -> list[str]:
    """Ambil daftar saham milik pengguna tertentu."""
    data = _load_data()
    return data.get(str(user_id), [])


def set_portfolio(user_id: str, tickers: list[str]) -> list[str]:
    """Tetapkan daftar saham baru untuk pengguna."""
    cleaned = []
    seen = set()
    for t in tickers:
        sym = clean_ticker(t)
        if sym and sym not in seen:
            seen.add(sym)
            cleaned.append(sym)

    data = _load_data()
    data[str(user_id)] = cleaned
    _save_data(data)
    return cleaned


def add_ticker(user_id: str, ticker: str) -> list[str]:
    """Tambahkan satu saham ke portofolio pengguna."""
    sym = clean_ticker(ticker)
    if not sym:
        return get_portfolio(user_id)
    current = get_portfolio(user_id)
    if sym not in current:
        current.append(sym)
        data = _load_data()
        data[str(user_id)] = current
        _save_data(data)
    return current


def remove_ticker(user_id: str, ticker: str) -> list[str]:
    """Hapus satu saham dari portofolio pengguna."""
    sym = clean_ticker(ticker)
    current = get_portfolio(user_id)
    updated = [s for s in current if s != sym]
    if len(updated) != len(current):
        data = _load_data()
        data[str(user_id)] = updated
        _save_data(data)
    return updated


def get_all_portfolios() -> dict[str, list[str]]:
    """Ambil seluruh portofolio pengguna untuk siklus broadcast ronda."""
    return _load_data()