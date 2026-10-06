# 🏘️ Siskamling Pasar

> **Pos ronda otomatis untuk investor ritel Indonesia.**
> Memantau saham mencurigakan di IDX setiap hari bursa — bukan saran investasi.

[![Track 2: Automation & Workflows](https://img.shields.io/badge/Sectors%20Hackathon-Track%202-blue)](https://hackathon.sectors.app)

## Problem Statement

Buat investor ritel pemula yang gampang FOMO sama saham viral, Siskamling Pasar ngecek otomatis tiap hari bursa: kenaikan harga saham beneran ditopang data atau nggak.

## Cara Kerja

```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐     ┌──────────┐
│  Cron 16:30 │────▶│ Sectors API  │────▶│ Skor Teknikal │────▶│ Telegram │
│  (Sn-Jum)   │     │ Top Gainers  │     │ Anti-Pom-Pom  │     │ Channel  │
└─────────────┘     │ Daily OHLCV  │     │ (0-100)       │     └──────────┘
                    └──────────────┘     │               │
                                         │ LLM Narator   │
                                         │ (opsional)    │
                                         └───────────────┘
```

**Alur per run:**
1. Ambil top gainers hari ini dari Sectors API
2. Untuk tiap saham, ambil data OHLCV harian (90 hari)
3. Hitung **skor anti-pom-pom** (deterministik, tanpa LLM):
   - Kenaikan harga 5 hari dan 20 hari vs ambang
   - Rasio volume vs rata-rata 20 hari
   - Posisi di rentang 90 hari (puncak?)
   - Gap naik, ekor atas panjang (ditolak di atas)
4. Skor ≥ 40 → masuk radar. LLM merangkum dalam bahasa warga (validator memastikan angka sesuai data)
5. Kirim ke Telegram + simpan run manifest (bukti unattended run)

## Backtest

Diuji terhadap **24 saham yang disuspensi BEI** karena "peningkatan harga kumulatif yang signifikan" (Agt–Okt 2026):

| Metrik | Nilai |
|--------|-------|
| Tertangkap | **24/24 (100%)** |
| Skor minimum | 44 |
| Skor rata-rata | 74 |
| Alarm muncul sebelum suspensi | rata-rata **7,4 hari** |
| False positive (10 blue chip × 40 hari) | **0%** |

⚠️ Sampel kecil, bukan jaminan akurasi. Ambang skor ditetapkan sebelum backtest, bukan di-fit dari hasil.

## Fitur

- 🔔 **Broadcast harian** — otomatis tiap 16:30 WIB hari bursa
- 🔍 **`/ronda TICKER`** — cek skor satu saham secara interaktif
- 🤖 **LLM narator** — bahasa santai ala hansip, dengan validator angka
- 📋 **Run manifest** — JSON per run (timestamp, jumlah alert, error) sebagai bukti otomatis
- 💾 **Cache disk** — hemat kredit API, data fundamental di-cache

## Setup

```bash
git clone https://github.com/diwanparker/siskamling-pasar.git
cd siskamling-pasar
cp .env.example .env
# Isi .env dengan API key Sectors, token bot Telegram, dll.

# Tes skor satu saham
python3 -m siskamling.bot --test BBCA

# Jalankan bot polling (interaktif)
python3 -m siskamling.bot --poll

# Broadcast manual (CLI)
python3 -m siskamling.bot --broadcast

# Cron (tambah ke crontab -e)
30 16 * * 1-5 /path/to/siskamling-pasar/run_broadcast.sh
```

## Otomasi n8n (Visual UI Workflow)

Untuk kolaborasi tim atau pengguna yang ingin memantau dan mengontrol jadwal patroli secara visual:
1. Buka dashboard n8n (misalnya `http://localhost:5678`).
2. Pilih menu **Workflows** ➔ **Add workflow** ➔ ikon titik tiga (**...**) di kanan atas ➔ **Import from File**.
3. Pilih file `workflows/siskamling_patrol_workflow.json` dari repositori ini.
4. Buka node **Configuration** untuk menyesuaikan variabel tanpa perlu menyentuh kode Python (`alert_threshold`, `n_gainers`, `fetch_days`).
5. Klik **Publish / Activate** untuk mengaktifkan scheduler otomatis pukul 16:30 WIB setiap hari bursa, atau klik tombol **Test Patrol On-Demand** untuk eksekusi langsung.

## Struktur

```
siskamling-pasar/
├── siskamling/
│   ├── sectors.py      # Client Sectors API v2 (stdlib, cache disk)
│   ├── score.py        # Skor teknikal anti-pom-pom (deterministik)
│   ├── narrator.py     # LLM narator + validator angka + fallback template
│   ├── backtest.py     # Point-in-time backtest vs suspensi BEI
│   └── bot.py          # Bot Telegram (polling + broadcast + manifest)
├── workflows/
│   └── siskamling_patrol_workflow.json  # Workflow visual n8n
├── tests/              # Unit test deterministik
├── data/
│   ├── backtest_result.json
│   ├── controls.json
│   └── suspensions.json
├── runs/               # Run manifest per hari (git-ignored)
├── run_broadcast.sh    # Entry point cron
├── .env.example
└── .gitignore
```

## Tech Stack

- **Python 3** (stdlib saja, tanpa pip install)
- **Sectors API v2** — OHLCV harian, top gainers, suspensi
- **LLM** via OpenAI-compatible API (9router/dll) — opsional, ada fallback template
- **Telegram Bot API** — broadcast + interaktif
- **Cron** — scheduler harian

## Disclaimer

⚠️ **Ini bukan saran investasi.** Siskamling Pasar hanya menyajikan data publik dari Sectors.app dengan perhitungan sederhana. Keputusan investasi sepenuhnya tanggung jawab pengguna. Tidak ada afiliasi dengan emiten atau BEI.

---

Dibuat untuk [Sectors Hackathon 2026](https://hackathon.sectors.app) — Track 2: Automation & Workflows.
