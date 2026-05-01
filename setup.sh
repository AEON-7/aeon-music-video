#!/usr/bin/env bash
# setup.sh — first-time install for aeon-music-video. CPU only, no GPU/ComfyUI required.
set -euo pipefail
[[ -f .env ]] && { set -a; source .env; set +a; }

c_red(){ printf '\033[31m%s\033[0m\n' "$*"; }
c_grn(){ printf '\033[32m%s\033[0m\n' "$*"; }
c_blu(){ printf '\033[36m%s\033[0m\n' "$*"; }

c_blu "==> aeon-music-video setup"

c_blu "[1/2] Python dependencies"
command -v python >/dev/null || { c_red "python not on PATH"; exit 1; }
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
c_grn "      ✓ deps installed"

c_blu "[2/2] ffmpeg + ffprobe"
ff="${FFMPEG:-ffmpeg}"; fp="${FFPROBE:-ffprobe}"
if command -v "$ff" >/dev/null && command -v "$fp" >/dev/null; then
    # Quick filter availability check
    if "$ff" -hide_banner -filters 2>/dev/null | grep -qE 'sendcmd|rgbashift'; then
        c_grn "      ✓ found, required filters present"
    else
        c_red "      ✗ ffmpeg present but missing sendcmd/rgbashift filters"
        c_red "        Install a full ffmpeg build (most apt/brew/static distributions are fine)"
        exit 1
    fi
else
    c_red "      ✗ ffmpeg or ffprobe missing"
    exit 1
fi

echo ""
c_grn "==> Setup complete."
c_blu "    Smoke test (drop in any audio + a video clip):"
echo '      python scripts/dmt_flash_editor.py --schedule schedule.json --audio song.flac -o out.mp4'
