"""LLM Narator Pos Ronda & Grounding Validator.

Prinsip:
- Perhitungan numerik 100% deterministik di Python.
- LLM hanya bertugas sebagai narator persona hansip ("Pak RT").
- Validator deterministik memastikan tidak ada halusinasi angka di narasi.
- Jika LLM gagal atau melanggar validasi, fallback template deterministik otomatis aktif.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import sectors  # Memastikan .env otomatis termuat jika ada

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Kamu adalah hansip pasar saham Indonesia bernama Pak RT.
Gaya bicara: santai, Indonesia sehari-hari (gue/lo), lucu tapi serius soal angka.
ATURAN MUTLAK:
- Hanya gunakan angka yang secara eksplisit ada di data JSON input. JANGAN menambah angka sendiri.
- Dilarang menyebut saran "beli" atau "jual". Ini bukan rekomendasi investasi.
- Akhiri selalu dengan: "⚠️ Ini bukan saran investasi. Data dari Sectors.app."
- Panjang maksimal 280 kata."""

FALLBACK_TEMPLATE = """\
{emoji} {symbol} — Skor Kentongan: {score}/100

{reasons}

Harga: {return_direction} ({sign}{absolute_return}%)
Volume: {volume_ratio}x dari rata-rata 20 hari

⚠️ Ini bukan saran investasi. Data dari Sectors.app."""

ALLOWED_STATIC_NUMERALS: set[str] = {"100", "0", "1", "2", "3", "20", "90", "5", "280"}


def extract_numbers_from_text(text: str) -> set[str]:
    """Ekstrak semua token numerik (desimal, negatif, bulat) dari teks."""
    return set(re.findall(r"-?\d+(?:\.\d+)?", text))


def collect_allowed_numbers(data: Any) -> set[str]:
    """Kumpulkan seluruh representasi angka yang sah dari payload input JSON."""
    numbers: set[str] = set()

    if isinstance(data, dict):
        for val in data.values():
            numbers |= collect_allowed_numbers(val)
    elif isinstance(data, list):
        for item in data:
            numbers |= collect_allowed_numbers(item)
    elif isinstance(data, str):
        numbers |= extract_numbers_from_text(data)
    elif isinstance(data, (int, float)):
        numbers.add(str(data))
        if isinstance(data, float):
            numbers.add(f"{data:.1f}")
            numbers.add(f"{data:.2f}")
            numbers.add(str(round(data * 100, 1)))  # Persentase 1 desimal
            numbers.add(str(round(data * 100)))     # Persentase bulat
            if data.is_integer():
                numbers.add(str(int(data)))

    return numbers


def validate_narration_grounding(narration: str, input_payload: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validasi deterministik: seluruh angka di teks narasi harus ada di payload data input.

    Returns:
        (is_valid, foreign_numbers_found)
    """
    allowed_numbers = collect_allowed_numbers(input_payload) | ALLOWED_STATIC_NUMERALS
    narration_numbers = extract_numbers_from_text(narration)
    foreign_numbers = [num for num in narration_numbers if num not in allowed_numbers]
    return len(foreign_numbers) == 0, foreign_numbers


def call_llm_api(data_payload: dict[str, Any], max_retries: int = 2) -> str | None:
    """Kirim permintaan ke LLM via OpenAI-compatible endpoint dengan validator grounding."""
    api_key = os.environ.get("LLM_API_KEY", os.environ.get("OPENAI_API_KEY", "")).strip()
    if not api_key:
        logger.debug("LLM_API_KEY tidak tersedia, menggunakan fallback template")
        return None

    base_url = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:20129/v1").rstrip("/")
    model_name = os.environ.get("LLM_MODEL", "hehe").strip()

    request_payload = json.dumps({
        "model": model_name,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Data kentongan hari ini:\n```json\n{json.dumps(data_payload, ensure_ascii=False)}\n```\nBuatkan laporan ronda.",
            },
        ],
        "temperature": 0.7,
        "max_tokens": 600,
        "stream": False,
    }).encode("utf-8")

    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=request_payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )

    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as resp:
                response_json = json.loads(resp.read().decode("utf-8"))

            content = response_json["choices"][0]["message"]["content"].strip()
            is_valid, foreign_nums = validate_narration_grounding(content, data_payload)

            if is_valid:
                return content

            logger.warning("LLM narasi ditolak (angka halusinasi: %s). Percobaan %d/%d", foreign_nums, attempt + 1, max_retries + 1)
        except Exception as error:
            logger.warning("Gagal memanggil LLM (percobaan %d/%d): %s", attempt + 1, max_retries + 1, error)

    return None


def generate_fallback_narration(symbol: str, score: int, reasons: list[str], features: dict[str, Any]) -> str:
    """Template deterministik tanpa LLM untuk memastikan output selalu tersedia."""
    ret_1d = features.get("return_1d", features.get("ret_1d", 0.0))
    vol_ratio = features.get("volume_ratio", features.get("vol_ratio", 0.0))

    emoji = "🚨" if score >= 70 else "🟡" if score >= 40 else "🛡️"
    reasons_text = "• " + "\n• ".join(reasons) if reasons else "(tidak ada indikasi risiko kuat)"

    return FALLBACK_TEMPLATE.format(
        emoji=emoji,
        symbol=symbol.replace(".JK", ""),
        score=score,
        reasons=reasons_text,
        return_direction="naik" if ret_1d >= 0 else "turun",
        sign="+" if ret_1d >= 0 else "",
        absolute_return=round(abs(ret_1d) * 100, 1),
        volume_ratio=round(vol_ratio, 1),
    )


def narrate(symbol: str, score: int, reasons: list[str], features: dict[str, Any]) -> str:
    """Fasade utama narasi: Coba LLM dengan grounding validator, fallback jika gagal."""
    ret_1d = features.get("return_1d", features.get("ret_1d", 0.0))
    ret_5d = features.get("return_5d", features.get("ret_5d", 0.0))
    ret_20d = features.get("return_20d", features.get("ret_20d", 0.0))
    vol_ratio = features.get("volume_ratio", features.get("vol_ratio", 0.0))
    pos_90d = features.get("position_90d", features.get("pos_90d", 0.0))
    at_high = features.get("is_at_90d_high", features.get("at_90d_high", False))

    clean_summary = {
        "naik_hari_ini": f"{round(ret_1d * 100, 1)}%",
        "naik_5_hari": f"{round(ret_5d * 100, 1)}%",
        "naik_20_hari": f"{round(ret_20d * 100, 1)}%",
        "lonjakan_volume": f"{round(vol_ratio, 1)}x",
        "posisi_rentang_90_hari": f"{round(pos_90d * 100, 1)}%",
        "di_puncak_90_hari": at_high,
    }

    payload = {
        "symbol": symbol,
        "score": score,
        "alasan": reasons,
        "ringkasan_fitur": clean_summary,
    }

    llm_output = call_llm_api(payload)
    if llm_output:
        return llm_output

    return generate_fallback_narration(symbol, score, reasons, features)


# Alias kompatibilitas
validate_narration = validate_narration_grounding
call_llm = call_llm_api
fallback = generate_fallback_narration
