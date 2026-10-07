# 🏘️ Siskamling Pasar

> **Pos ronda otomatis untuk investor ritel Indonesia.**
> Memantau saham mencurigakan di IDX setiap hari bursa — bukan saran investasi.

[![Track 2: Automation & Workflows](https://img.shields.io/badge/Sectors%20Hackathon-Track%202-blue)](https://hackathon.sectors.app)

## Problem Statement

Buat investor ritel pemula yang gampang FOMO sama saham viral, Siskamling Pasar ngecek otomatis tiap hari bursa: kenaikan harga saham beneran ditopang data atau nggak.

## Cara Kerja

```
Cron / n8n ──HTTP──▶ Siskamling API (FastAPI) ──▶ Sectors API (OHLCV + fundamental)
                            │
                            ├─ Skor teknikal deterministik (0-100)  → patroli risiko sore
                            ├─ Screening fundamental deterministik   → briefing pagi
                            └─▶ Telegram / Discord (laporan terbaca)
```

**Dua pipeline harian:**

**A. Patroli Risiko Sore (16:30 WIB)**

1. Ambil top gainers hari ini dari Sectors API
2. Untuk tiap saham, ambil data OHLCV harian (90 hari)
3. Hitung **skor anti-pom-pom** (deterministik, tanpa LLM):
   - Kenaikan harga 5 hari dan 20 hari vs ambang
   - Rasio volume vs rata-rata 20 hari
   - Posisi di rentang 90 hari (puncak?)
   - Gap naik, ekor atas panjang (ditolak di atas)
4. Skor ≥ 40 → masuk radar. Laporan disusun deterministik jadi papan skor peringkat + bullet metrik tiap saham
5. Broadcast ke Telegram/Discord + simpan run manifest (bukti unattended run)

**B. Briefing Pagi (08:30 WIB)**

1. Ambil universe saham dari Companies Screener Sectors API
2. Untuk tiap kandidat, ambil Company Report (overview, valuation, dividend, financials)
3. Saring **deterministik** (tanpa LLM): laba positif, PE ≤ ambang, dividend yield ≥ ambang
4. Peringkat berdasarkan dividend yield, ambil top-N kandidat
5. Broadcast "Briefing Pagi" + simpan manifest

## Backtest

Diuji terhadap **24 saham yang disuspensi BEI** karena "peningkatan harga kumulatif yang signifikan" (Agt–Okt 2026):

| Metrik                                  | Nilai                  |
| --------------------------------------- | ---------------------- |
| Tertangkap                              | **24/24 (100%)**       |
| Skor minimum                            | 44                     |
| Skor rata-rata                          | 74                     |
| Alarm muncul sebelum suspensi           | rata-rata **7,4 hari** |
| False positive (10 blue chip × 40 hari) | **0%**                 |

⚠️ Sampel kecil, bukan jaminan akurasi. Ambang skor ditetapkan sebelum backtest, bukan di-fit dari hasil.

## Fitur

- 🔌 **HTTP API (FastAPI)** — `POST /patrol`, `POST /morning-brief`, `GET /ronda/{ticker}`. Otomasi (n8n/cron eksternal) cukup memanggil endpoint, tanpa subprocess
- 🔔 **Patroli risiko harian** — top gainers dipindai tiap 16:30 WIB hari bursa
- 🌅 **Briefing pagi** — screening fundamental deterministik (PE, dividend yield, laba) tiap 08:30 WIB
- 🔍 **`/ronda TICKER`** — cek skor satu saham secara interaktif
- 💬 **Multi-platform (Open/Closed)** — siaran & perintah `/ronda` jalan di **Telegram** _dan_ **Discord**. Menambah platform baru cukup bikin satu subclass `Channel` + `@register_channel`, tanpa mengubah kode dispatch
- 📊 **Laporan terbaca** — papan skor peringkat + bullet metrik, langsung enak dibaca di Telegram/Discord
- 📋 **Run manifest** — JSON per run (timestamp, jumlah alert/kandidat, error) sebagai bukti otomatis
- 🧾 **Log otomasi** — `logs/automation.jsonl` (append-only, ikut di-commit) mencatat tiap run terjadwal: waktu, pipeline, trigger (cron/api/manual), run_id, dan ringkasan hasil

## Setup

```bash
git clone https://github.com/diwanparker/siskamling-pasar.git
cd siskamling-pasar
cp .env.example .env
# Isi .env dengan API key Sectors, token bot Telegram, dll.

# HTTP API butuh dependensi tambahan (opsional; CLI inti tetap stdlib murni):
pip install -r requirements.txt

# Tes skor satu saham
python3 -m siskamling.bot --test BBCA

# Jalankan HTTP API
python3 -m siskamling.bot --serve --host 0.0.0.0 --port 8000

# Briefing pagi (screening fundamental) manual
python3 -m siskamling.bot --morning-brief --json

# Broadcast ronda manual
python3 -m siskamling.bot --broadcast --json

# Bot polling (interaktif)
python3 -m siskamling.bot --poll

# Cron (tambah ke crontab -e)
30 8  * * 1-5 /path/to/siskamling-pasar/run_morning_brief.sh
30 16 * * 1-5 /path/to/siskamling-pasar/run_broadcast.sh
```

## HTTP API

Dijalankan dengan `python3 -m siskamling.bot --serve` (setara `uvicorn siskamling.api:app`).

| Method | Path              | Deskripsi                                                         |
| ------ | ----------------- | ----------------------------------------------------------------- |
| `GET`  | `/health`         | Cek kesehatan server                                              |
| `POST` | `/patrol`         | Jalankan patroli risiko sore + broadcast, kembalikan run manifest |
| `POST` | `/morning-brief`  | Jalankan briefing pagi + broadcast, kembalikan manifest           |
| `GET`  | `/ronda/{ticker}` | Hitung skor risiko satu saham                                     |

Endpoint **tidak terikat pada Telegram/Discord**. Setiap respons selalu memuat `messages` — narasi teks polos siap baca — jadi bisa di-curl **tanpa kredensial kanal apa pun**. Tambahkan `"dry_run": true` untuk memastikan tidak ada pesan yang dikirim ke kanal.

Body request opsional (kosong = pakai default/env):

```bash
# Patroli risiko — cukup tampilkan narasi, tanpa kirim ke kanal
curl -X POST 'http://localhost:8000/patrol' \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true, "n_gainers": 20}'
# → {"n_alerts": 3, "messages": ["🔔 Laporan Ronda Sore — ...", "🚨 BBCA — ...", ...], ...}

# Briefing pagi
curl -X POST 'http://localhost:8000/morning-brief' \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true, "n_candidates": 3, "max_pe": 20, "min_dividend_yield": 5}'

# Skor satu saham (respons memuat "narration")
curl 'http://localhost:8000/ronda/BBCA'
```

Dokumentasi interaktif tersedia di `http://localhost:8000/docs`.

## Otomasi n8n (Visual UI Workflow)

Workflow memanggil **HTTP API** Siskamling (bukan subprocess). Pastikan server API berjalan lebih dulu.

1. Jalankan API: `python3 -m siskamling.bot --serve --host 0.0.0.0 --port 8000`.
2. Buka dashboard n8n, pilih **Workflows** ➔ **Add workflow** ➔ **...** ➔ **Import from File**.
3. Pilih `workflows/siskamling_patrol_workflow.json`.
4. Buka node **Configuration** / **Configuration Morning Brief** untuk menyesuaikan `api_base_url`, `alert_threshold`, `n_gainers`, `n_candidates`, `max_pe`, `min_dividend_yield` tanpa menyentuh kode.
5. Klik **Publish / Activate** untuk scheduler otomatis (08:30 & 16:30 WIB), atau **Test Patrol On-Demand** untuk eksekusi langsung.

## Bukti Otomasi (Log Unattended Run)

Setiap pipeline selesai — dipicu **cron**, **n8n** (lewat HTTP API), maupun manual — bot menulis **satu baris JSON** ke `logs/automation.jsonl` (append-only):

```json
{"logged_at": "2026-10-07T09:30:00+00:00", "pipeline": "morning-brief", "trigger": "cron", "dry_run": false, "run_id": "a1b2c3d4e5f6", "started_at": "...", "finished_at": "...", "duration_seconds": 4.21, "summary": {"n_universe_scanned": 30, "n_candidates": 3, "portfolio_stocks_scanned": 5, "n_errors": 0}}
```

- `trigger` bernilai `cron` (crontab), `api` (n8n / HTTP), atau `manual`.
- Berkas ini **sengaja TIDAK di-gitignore** agar riwayat run terjadwal bisa ikut di-commit sebagai bukti workflow berjalan sendiri.
- Lihat isinya: `cat logs/automation.jsonl` atau `tail -n 20 logs/automation.jsonl`.
- Manifest detail per hari tetap tersimpan di `runs/` (git-ignored, bersifat lokal).

## Struktur

```
siskamling-pasar/
├── siskamling/
│   ├── sectors.py      # Client Sectors API v2 (stdlib, cache disk) + screener & company report
│   ├── score.py        # Skor teknikal anti-pom-pom (deterministik)
│   ├── narrator.py     # Narator deterministik (bullet laporan & briefing, tanpa LLM)
│   ├── backtest.py     # Point-in-time backtest vs suspensi BEI
│   ├── bot.py          # Orkestrasi: skoring, briefing, broadcast, CLI
│   ├── api.py          # HTTP API (FastAPI)
│   └── platforms/      # Abstraksi kanal (Open/Closed Principle)
│       ├── base.py            # Channel/InteractiveChannel, router, dispatch bersama
│       ├── telegram.py        # Kanal Telegram (polling)
│       ├── discord.py         # Kanal Discord (REST + slash command)
│       └── discord_gateway.py # Transport WebSocket Discord Gateway (stdlib)
├── workflows/
│   └── siskamling_patrol_workflow.json  # Workflow visual n8n (HTTP API)
├── tests/              # Unit test deterministik (+ test API)
├── data/
│   ├── backtest_result.json
│   ├── controls.json
│   └── suspensions.json
├── runs/               # Run manifest per hari (git-ignored, lokal)
├── logs/               # Log otomasi append-only (ikut di-commit sebagai bukti)
├── run_broadcast.sh    # Entry point cron (patroli sore, --trigger cron)
├── run_morning_brief.sh # Entry point cron (briefing pagi, --trigger cron)
├── requirements.txt    # Dependensi HTTP API (FastAPI/uvicorn)
├── .env.example
└── .gitignore
```

## Tech Stack

- **Python 3** — orkestrasi inti stdlib murni; HTTP API memakai FastAPI + uvicorn
- **Sectors API v2** — OHLCV harian, top gainers, screener, company report
- **FastAPI + uvicorn** — HTTP API untuk otomasi (n8n/cron eksternal)
- **Telegram Bot API** — broadcast + interaktif
- **Discord Bot API + Gateway** — broadcast + slash command interaktif (WebSocket stdlib)
- **Cron** — scheduler harian

## Development & Panduan Tim

Untuk alur kerja harian tim, standar pembuatan branch, pengujian (TDD), serta panduan kolaborasi dan deployment, silakan lihat [DEVELOPMENT.md](DEVELOPMENT.md).

## Disclaimer

⚠️ **Ini bukan saran investasi.** Siskamling Pasar hanya menyajikan data publik dari Sectors.app dengan perhitungan sederhana. Keputusan investasi sepenuhnya tanggung jawab pengguna. Tidak ada afiliasi dengan emiten atau BEI.

---

Dibuat untuk [Sectors Hackathon 2026](https://hackathon.sectors.app) — Track 2: Automation & Workflows.
