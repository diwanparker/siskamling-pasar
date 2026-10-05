"""LLM narator pos ronda — rangkum skor jadi bahasa warga.

Validator: semua angka di output LLM harus ada di input JSON.
Kalau validator gagal, pakai template fallback (tanpa LLM).
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

_BASE = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:20129/v1")
_MODEL = os.environ.get("LLM_MODEL", "hehe")

SYSTEM_PROMPT = """\
Kamu adalah hansip pasar saham Indonesia bernama Pak RT.
Gaya bicara: santai, Indonesia sehari-hari (gue/lo), lucu tapi serius soal angka.
ATURAN MUTLAK:
- Hanya pakai angka yang ada di data JSON di bawah. JANGAN menambah angka sendiri.
- Jangan sebut "beli" atau "jual". Ini bukan rekomendasi investasi.
- Akhiri dengan: "⚠️ Ini bukan saran investasi. Data dari Sectors.app."
- Maksimal 280 kata."""

FALLBACK_TEMPLATE = """\
{emoji} {symbol} — Skor Kentongan: {score}/100

{reasons}

Harga: {ret_pct} ({direction} {abs_ret}%)
Volume: {vol_ratio}x dari rata-rata 20 hari

⚠️ Ini bukan saran investasi. Data dari Sectors.app."""


def _extract_numbers(text: str) -> set[str]:
    """Ambil semua angka (termasuk desimal dan negatif) dari teks."""
    return set(re.findall(r"-?\d+(?:\.\d+)?", text))


def _numbers_in_data(data: dict) -> set[str]:
    """Rekursif ambil semua angka dari dict/list."""
    nums = set()
    if isinstance(data, dict):
        for v in data.values():
            nums |= _numbers_in_data(v)
    elif isinstance(data, list):
        for v in data:
            nums |= _numbers_in_data(v)
    elif isinstance(data, (int, float)):
        nums.add(str(data))
        if isinstance(data, float):
            nums.add(f"{data:.1f}")
            nums.add(f"{data:.2f}")
            nums.add(str(round(data * 100, 1)))  # persen
            nums.add(str(round(data * 100)))
    return nums


def validate_narration(narration: str, input_data: dict) -> tuple[bool, list[str]]:
    """Cek semua angka di narasi ada di input. Return (ok, angka_asing)."""
    allowed = _numbers_in_data(input_data)
    # Tambah angka umum yang boleh (tahun, tanggal, konstanta)
    allowed |= {"100", "0", "1", "2", "3", "20", "90", "5", "280"}
    narr_nums = _extract_numbers(narration)
    foreign = [n for n in narr_nums if n not in allowed]
    return len(foreign) == 0, foreign


def call_llm(data: dict, max_retries: int = 2) -> str | None:
    """Panggil LLM via OpenAI-compatible API. Return narasi atau None."""
    key = os.environ.get("LLM_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
    if not key:
        return None
    payload = json.dumps({
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Data kentongan hari ini:\n```json\n{json.dumps(data, ensure_ascii=False)}\n```\nBuatkan laporan ronda."},
        ],
        "temperature": 0.7,
        "max_tokens": 600,
    }).encode()
    req = urllib.request.Request(
        f"{_BASE}/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())
            text = body["choices"][0]["message"]["content"].strip()
            ok, foreign = validate_narration(text, data)
            if ok:
                return text
            if attempt < max_retries:
                continue  # retry, LLM sering berhasil di coba ke-2
            return None  # gagal validasi setelah retry
        except (urllib.error.URLError, KeyError, json.JSONDecodeError):
            if attempt < max_retries:
                continue
            return None
    return None


def fallback(symbol: str, score: int, why: list[str], feat: dict) -> str:
    """Template tanpa LLM — angka pasti dari data."""
    ret = feat.get("ret_1d", 0)
    emoji = "🚨" if score >= 70 else "🟡" if score >= 40 else "🛡️"
    return FALLBACK_TEMPLATE.format(
        emoji=emoji, symbol=symbol.replace(".JK", ""), score=score,
        reasons="• " + "\n• ".join(why) if why else "(tidak ada sinyal kuat)",
        ret_pct="naik" if ret >= 0 else "turun",
        direction="+" if ret >= 0 else "",
        abs_ret=round(abs(ret) * 100, 1),
        vol_ratio=round(feat.get("vol_ratio", 0), 1),
    )


def narrate(symbol: str, score: int, why: list[str], feat: dict) -> str:
    """Coba LLM dulu, fallback ke template kalau gagal."""
    data = {"symbol": symbol, "score": score, "alasan": why, "fitur": feat}
    llm_result = call_llm(data)
    if llm_result:
        return llm_result
    return fallback(symbol, score, why, feat)
