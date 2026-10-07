#!/bin/bash
# Siskamling Pasar — broadcast harian
# Dipanggil cron: 30 16 * * 1-5 (16:30 WIB, Senin-Jumat)
set -euo pipefail
cd "$(dirname "$0")"
set -a; . .env; set +a
export PYTHONPATH="$PWD"
python3 -m siskamling.bot --broadcast --trigger cron >> runs/cron.log 2>&1
