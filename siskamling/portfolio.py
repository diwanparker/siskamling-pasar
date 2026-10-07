"""Modul manajemen portofolio dan watchlist saham warga (personal asset tracking)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PORTFOLIO_FILE = Path(__file__).resolve().parent.parent / "data" / "portofolio.json"


RESERVED_WORDS = {"ASET", "PORTOFOLIO", "PORTFOLIO", "WATCHLIST", "TAMBAH", "HAPUS", "LIST", "HELP", "START"}


def clean_ticker(ticker: str) -> str:
    """Normalisasi kode ticker IDX menjadi format TICKER.JK."""
    cleaned = ticker.strip().upper().rstrip(",.;:")
    if not cleaned:
        return ""
    base = cleaned.replace(".JK", "")
    if base in RESERVED_WORDS:
        return ""
    if cleaned.endswith(".JK"):
        return cleaned
    return f"{cleaned}.JK"


def scope_user_key(platform: str, user_id: str) -> str:
    """Bentuk kunci penyimpanan ber-prefiks platform (mis. "telegram:12345").

    Prefiks diperlukan agar broadcast per-user tahu kanal mana yang harus dipakai.
    Bila `platform` kosong, kunci dibiarkan apa adanya (kompatibel dengan data lama).
    """
    normalized_id = str(user_id or "default")
    return f"{platform}:{normalized_id}" if platform else normalized_id


def parse_user_key(user_key: str) -> tuple[str, str]:
    """Pisahkan kunci portofolio menjadi (platform, user_id); platform kosong bila tanpa prefiks."""
    platform, separator, user_id = str(user_key).partition(":")
    if not separator:
        return "", platform
    return platform, user_id


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
    """Ambil seluruh portofolio pengguna untuk siklus broadcast ronda (dideduplikasi per platform & user)."""
    raw_data = _load_data()
    deduped: dict[str, list[str]] = {}
    needs_rewrite = False

    # Prioritaskan kunci ber-prefiks (mis. 'telegram:123') daripada unprefixed ('123')
    for key, tickers in raw_data.items():
        platform, recipient = parse_user_key(key)
        normalized_platform = platform or "telegram"
        normalized_key = f"{normalized_platform}:{recipient}"

        if normalized_key in deduped:
            needs_rewrite = True
            # Jika kunci saat ini ber-prefiks eksplisit, gunakan data ber-prefiks
            if platform:
                deduped[normalized_key] = tickers
        else:
            if not platform:
                needs_rewrite = True
            deduped[normalized_key] = tickers

    if needs_rewrite:
        _save_data(deduped)

    return deduped