"""Client tipis untuk Sectors API v2 (stdlib saja).

Catatan hasil probe:
- Header Authorization berisi key mentah (tanpa "Bearer").
- User-Agent kustom WAJIB, kalau tidak Cloudflare menjawab 1010.
- Semua respons mentah di-cache ke disk supaya backtest tidak menghabiskan kredit dua kali.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://api.sectors.app"
UA = "siskamling-pasar/0.1 (+hackathon)"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"


class SectorsError(RuntimeError):
    pass


def _key() -> str:
    key = os.environ.get("SECTORS_API_KEY", "").strip()
    if not key:
        raise SectorsError("SECTORS_API_KEY belum di-set (lihat .env.example)")
    return key


def get(path: str, params: dict | None = None, *, cache: bool = True, retries: int = 2):
    """GET JSON. Mengembalikan objek hasil parse. Error dilempar apa adanya."""
    qs = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
    url = f"{BASE}{path}" + (f"?{qs}" if qs else "")
    ckey = hashlib.sha1(url.encode()).hexdigest()[:20]
    cfile = CACHE_DIR / f"{ckey}.json"
    if cache and cfile.exists():
        return json.loads(cfile.read_text())

    req = urllib.request.Request(
        url,
        headers={"Authorization": _key(), "User-Agent": UA, "Accept": "application/json"},
    )
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            if cache:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cfile.write_text(json.dumps(data))
            return data
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:200]
            if e.code in (429, 500, 502, 503) and attempt < retries:
                time.sleep(2 * (attempt + 1))
                last = e
                continue
            raise SectorsError(f"HTTP {e.code} {path}: {body}") from e
        except urllib.error.URLError as e:
            last = e
            time.sleep(2)
    raise SectorsError(f"gagal {path}: {last}")


def suspensions(start: str, limit: int = 100, page: int | None = None):
    return get("/v2/suspensions/", {"start": start, "limit": limit, "page": page})


def daily(symbol: str, start: str, end: str):
    return get(f"/v2/daily/{symbol}/", {"start": start, "end": end})
