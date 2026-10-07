#!/bin/bash
# Siskamling Pasar — briefing pagi (screening fundamental)
# Dipanggil cron: 30 8 * * 1-5 (08:30 WIB, Senin-Jumat)
set -euo pipefail
cd "$(dirname "$0")"
set -a; . .env; set +a
export PYTHONPATH="$PWD"
python3 -m siskamling.bot --morning-brief --trigger cron >> runs/morning-cron.log 2>&1
