"""Client Sectors API v2 (stdlib saja).

Catatan:
- Header Authorization berisi key mentah (tanpa "Bearer").
- User-Agent kustom wajib untuk melewati Cloudflare.
- Respons mentah di-cache ke disk untuk hemat kuota dan determinisme.
- Normalisasi bar (open/close/volume) otomatis dilakukan di layer ini.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sectors.app"
USER_AGENT = "siskamling-pasar/0.1 (+hackathon)"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"


def load_env_defaults() -> None:
    """Muat variabel lingkungan dari file .env di root proyek jika belum di-set."""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return
    try:
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key, val = stripped.split("=", 1)
                os.environ.setdefault(key.strip().lstrip("\ufeff"), val.strip())
    except OSError as error:
        logger.debug("File .env tidak dapat dibaca: %s", error)


load_env_defaults()


class SectorsError(RuntimeError):
    """Kesalahan saat memanggil Sectors API."""


def get_api_key() -> str:
    """Ambil API key dari environment variable."""
    key = os.environ.get("SECTORS_API_KEY", "").strip()
    if not key:
        raise SectorsError("SECTORS_API_KEY belum di-set (lihat .env.example)")
    return key


def get(path: str, params: dict[str, Any] | None = None, *, cache: bool = True, retries: int = 2) -> Any:
    """GET JSON endpoint dari Sectors API dengan caching disk dan retry."""
    query_string = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
    url = f"{BASE_URL}{path}" + (f"?{query_string}" if query_string else "")

    cache_key = hashlib.sha1(url.encode()).hexdigest()[:20]
    cache_file = CACHE_DIR / f"{cache_key}.json"
    if cache and cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as read_error:
            logger.warning("Gagal membaca cache %s: %s", cache_file, read_error)

    req = urllib.request.Request(
        url,
        headers={"Authorization": get_api_key(), "User-Agent": USER_AGENT, "Accept": "application/json"},
    )

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if cache:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(data), encoding="utf-8")
            return data
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")[:200]
            if error.code in (429, 500, 502, 503) and attempt < retries:
                time.sleep(2 * (attempt + 1))
                last_error = error
                continue
            raise SectorsError(f"HTTP {error.code} {path}: {body}") from error
        except urllib.error.URLError as error:
            last_error = error
            time.sleep(2)

    raise SectorsError(f"Gagal memanggil {path} setelah {retries} retry: {last_error}")


def clean_daily_bars(raw_bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bersihkan data bar harian:

    - Pastikan close dan volume ada.
    - Isi open dengan close jika open 0 atau kosong (misal bar suspensi).
    - Urutkan kronologis berdasarkan tanggal.
    """
    cleaned: list[dict[str, Any]] = []
    for raw_bar in raw_bars:
        if raw_bar.get("close") is not None and raw_bar.get("volume") is not None:
            bar = dict(raw_bar)
            if not bar.get("open"):
                bar["open"] = bar["close"]
            cleaned.append(bar)
    cleaned.sort(key=lambda b: str(b.get("date", "")))
    return cleaned


def suspensions(start: str, limit: int = 100, page: int | None = None) -> dict[str, Any]:
    """Ambil daftar suspensi bursa sejak tanggal start."""
    return get("/v2/suspensions/", {"start": start, "limit": limit, "page": page})


def daily(symbol: str, start: str, end: str, *, clean: bool = True) -> list[dict[str, Any]]:
    """Ambil data transaksi harian (OHLCV) saham."""
    clean_symbol = symbol.upper().replace(".JK", "")
    raw = get(f"/v2/daily/{clean_symbol}/", {"start": start, "end": end})
    if not isinstance(raw, list):
        return []
    return clean_daily_bars(raw) if clean else raw


def screener(
    where: str | None = None,
    order_by: str = "-market_cap",
    limit: int = 50,
    offset: int = 0,
    *,
    include_query_values: bool = True,
    cache: bool = True,
) -> list[dict[str, Any]]:
    """Saring perusahaan via Companies Screener (`/v2/companies/`).

    `where` memakai klausa SQL-like (mis. `"market_cap IS NOT NULL"`).
    Mengembalikan daftar `results` (symbol, company_name, query_values).
    """
    params: dict[str, Any] = {
        "where": where,
        "order_by": order_by,
        "limit": limit,
        "offset": offset,
        "include_query_values": "true" if include_query_values else "false",
    }
    response = get("/v2/companies/", params, cache=cache)
    results = response.get("results") if isinstance(response, dict) else None
    return results if isinstance(results, list) else []


def company_report(symbol: str, sections: list[str] | None = None) -> dict[str, Any]:
    """Ambil Company Report (`/v2/company/report/{symbol}/`) untuk bagian terpilih.

    `sections` mis. `["overview", "valuation", "dividend", "financials"]`.
    """
    clean_symbol = symbol.upper().replace(".JK", "")
    params = {"sections": ",".join(sections)} if sections else None
    response = get(f"/v2/company/report/{clean_symbol}/", params)
    return response if isinstance(response, dict) else {}
