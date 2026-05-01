#!/usr/bin/env bash
# sync.sh — incremental update for aeon-music-video.
set -euo pipefail
[[ -f .env ]] && { set -a; source .env; set +a; }

c_blu(){ printf '\033[36m%s\033[0m\n' "$*"; }
c_grn(){ printf '\033[32m%s\033[0m\n' "$*"; }

c_blu "==> aeon-music-video sync"

c_blu "[1/2] git pull"
git pull --ff-only

c_blu "[2/2] pip install -r requirements.txt"
python -m pip install --quiet -r requirements.txt
c_grn "      ✓ deps up to date"

echo ""
c_grn "==> sync complete"
