# AGENTS.md — aeon-music-video

Instructions for AI agents that operate this tool.

## Step 0 — This tool is local-only

Unlike its sibling repos in AEON Media Production, this one has **no ComfyUI dependency** and **no remote-execution path**. Always invoke directly:

```bash
python scripts/reactive_compositor.py --audio song.flac --mood-clip ... -o out.mp4
python scripts/dmt_flash_editor.py    --schedule schedule.json --audio song.flac -o out.mp4
```

No SSH commands, no HTTP calls, no model downloads. The user just needs ffmpeg on PATH and Python deps installed via `./setup.sh`.

If the user is running their primary work on a remote GPU box, they likely have audio/video files there that need to come back to a local machine before this tool can use them — instruct them to `scp` or sync the files locally first, then run this tool against the local copies.

## When to invoke

- User asks for an "audio-reactive music video" / "video that reacts to the song" / "beat-synced edit"
- User wants a "DMT flash" / "Tron aesthetic" / "rapid-cut vertical music video"
- User has clips + a song and needs them combined with reactive effects

## Setup contract

Run `./setup.sh` once. Idempotent. Verifies:
- Python deps installed (`requirements.txt`)
- ffmpeg + ffprobe on PATH (or `FFMPEG`/`FFPROBE` env vars)
- librosa import works

No ComfyUI required, no models to download. This repo is pure CPU + ffmpeg.

## Invocation contract

### Smooth music video (`reactive_compositor.py`)

Use when:
- User wants a longer-form music video (1–4 min)
- Mood-driven editing — different sections of the song should feel different visually
- Crossfades between clips, not hard cuts

```bash
python scripts/reactive_compositor.py \
    --audio  <song>.flac \
    --mood-clip <bucket>:<clip>.mp4   # repeat per bucket: calm, cosmic, building, crystalline, deep, explosive
    --output <out>.mp4 \
    --fps 24 --width 832 --height 480
```

Mood buckets are documented in `SKILL.md`. If you only have a flat list of clips (no bucket info), use `--clip <path>` repeatedly and the compositor distributes them by inferred segment intensity.

### Hard-cut DMT mode (`dmt_flash_editor.py`)

Use when:
- User wants short-form (15–30 s), high-energy, rapid-cut content
- Vertical 720×1280 default (TikTok / Reels / Shorts format)
- Aggressive aesthetic — chromatic aberration, bloom, brightness strobing on every beat

```bash
# Build a schedule first — clip path + trim_start + duration per cut
cat > schedule.json <<EOF
[
  {"clip_path": "clip_01.mp4", "trim_start": 0.2, "duration": 2.0},
  {"clip_path": "clip_02.mp4", "trim_start": 0.5, "duration": 1.0}
]
EOF

python scripts/dmt_flash_editor.py \
    --schedule schedule.json \
    --audio    <song>.flac \
    --output   <out>.mp4 \
    --width 720 --height 1280
```

## Companion workflows

The natural pipeline is:

1. **Audio**: `aeon-music-maker` → `song.flac`
2. **Source clips**: `aeon-movie-maker` (LTX 2.3 fast cinematic) or any other source
3. **This repo**: ties them together with reactive effects

If the user is starting from scratch and asks for a complete music video, walk them through all three steps. If they already have audio and clips, jump straight to step 3.

## Failure modes

| Symptom | Fix |
|---|---|
| Video freezes ~20 s in | Already fixed in code — uses `-stream_loop -1` at demuxer level instead of the broken `loop` filter |
| `sendcmd` "Missing separator" error | Don't hand-edit the sendcmd files; the scripts emit valid syntax |
| Brightness flashes look stepped | Lower `--brightness-peak` (default 0.7 for DMT, 0.25 for smooth) |
| Hue rotation too aggressive | Lower `--hue-deg` / `--hue-max-deg` |
| Audio out of sync with video | Verify `--fps` matches the source clips' fps (default 24) |
| Output too quiet | Lower `--lufs` target (e.g. `-9` instead of `-12`) — but more loudness = less dynamic range |

## Tips for selecting clips

- For `reactive_compositor.py`: clip variety matters more than count. 3–6 distinct clips matched to mood buckets beats 12 similar ones.
- For `dmt_flash_editor.py`: each clip should have a clear visual identity in its first 2 s — that's typically all the viewer sees before the cut.
- Clips longer than the schedule duration are auto-trimmed via `trim_start`. Clips shorter than required are looped.
- Vertical clips for DMT mode (720×1280); horizontal for general (832×480 or 1920×1080).
