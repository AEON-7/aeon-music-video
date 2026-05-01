---
name: aeon-music-video
description: >
  Compose audio-reactive music videos from existing video clips and an audio track.
  USE THIS SKILL when the user wants to: build a music video from clips that
  react to the song's beats / onsets / spectral content, create rapid-cut
  hard-cut edits synced to a song, build a DMT-flash / Tron-aesthetic video,
  or compose a video where visuals respond to audio dynamics. Two scripts:
  reactive_compositor.py (general reactive editing across mood-bucketed clips)
  and dmt_flash_editor.py (10-cut hard-cut editor with chromatic aberration,
  bloom, and aggressive per-beat post-processing).
---

# aeon-music-video — Audio-Reactive Music Video Builder

Two complementary scripts for turning a music track + a pile of video clips into a finished music video. Both detect the audio's beats, onsets, RMS, and spectral centroid via librosa, then drive ffmpeg filter chains that pulse brightness, hue, zoom, and chromatic aberration in sync with the music.

## When to use which

| Need | Script |
|---|---|
| General music video — pick clips by mood, smooth crossfades, beat-pulsed effects | `reactive_compositor.py` |
| Rapid hard-cut edit — 8–12 clips at fixed durations, aggressive per-beat strobing | `dmt_flash_editor.py` |
| DMT / Tron / hyperkinetic aesthetic with chromatic aberration + bloom | `dmt_flash_editor.py` |

## Prerequisites

- Audio track (FLAC/WAV/MP3) — the song the video reacts to
- A pile of video clips (MP4, any duration) — what gets cut into the final video
- ffmpeg with `sendcmd`, `eq`, `hue`, `rgbashift`, `gblur`, `showcqt`, `avectorscope` filters (standard build is fine)
- Python 3.10+, librosa, numpy, scipy, soundfile

## reactive_compositor.py — general audio-reactive editor

Workflow:

1. **Analyze the audio** — librosa extracts beat times, onset envelope, RMS, spectral centroid
2. **Segment the audio** by intensity + brightness (continuous mood map)
3. **Match clips to segments by mood bucket** (calm / cosmic / building / crystalline / deep / explosive)
4. **Sequence clips** in order, with crossfades on intensity drops
5. **Apply reactive effects**:
   - `eq` filter brightness pulses on every beat (peak +0.25 by default)
   - `eq` saturation drives by RMS envelope
   - `hue` rotates by spectral centroid (warmer → cooler colors track frequency)
   - Optional zoom pulses on RMS peaks
6. **Optional overlays**: showcqt spectrum analyzer + avectorscope stereo image

### Usage

```bash
# Provide one clip per mood bucket
python scripts/reactive_compositor.py \
    --audio  song.flac \
    --mood-clip calm:cosmic_drift.mp4 \
    --mood-clip building:wireframe_grid.mp4 \
    --mood-clip explosive:fractal_burst.mp4 \
    --mood-clip crystalline:prism_shimmer.mp4 \
    --mood-clip deep:dark_tunnel.mp4 \
    --output  music_video.mp4 \
    --fps 24 --width 832 --height 480

# Or provide a flat list of clips and let the compositor distribute them
python scripts/reactive_compositor.py \
    --audio song.flac \
    --clip clip1.mp4 --clip clip2.mp4 --clip clip3.mp4 --clip clip4.mp4 \
    --output mv.mp4

# Reactive parameters
#   --zoom-peak 0.12        zoom pulse amplitude on RMS peaks (default 0.12)
#   --brightness-peak 0.25  brightness pulse on beats (default 0.25)
#   --hue-max-deg 30        hue rotation range from centroid (default 30°)
#   --no-cqt                disable spectrum analyzer overlay
#   --no-vectorscope        disable stereo vectorscope overlay
```

### Mood buckets

The compositor pre-defines six mood buckets. Clips are scored by `(intensity_mean, brightness_mean)` at 6-tuple ranges; matching clips get assigned to segments where both metrics fall in that bucket.

| Bucket | Intensity | Brightness | Use for |
|---|---|---|---|
| `calm` | 0.0–0.3 | 0.3–0.6 | quiet intros, breakdowns, ambient washes |
| `cosmic` | 0.2–0.5 | 0.4–0.7 | nebula / starfield / drifting / textural |
| `building` | 0.4–0.7 | 0.5–0.8 | wireframe / geometric / building energy |
| `crystalline` | 0.5–0.8 | 0.6–1.0 | sharp / prismatic / refractive / bright |
| `deep` | 0.4–0.7 | 0.0–0.4 | dark tunnels / underwater / submerged |
| `explosive` | 0.7–1.0 | 0.5–1.0 | fractals / starbursts / chaotic / drops |

## dmt_flash_editor.py — hard-cut rapid editor

Built for the Twitter-DMT-flash aesthetic: 8–12 clips, hard cuts every 1–2 s, aggressive per-beat brightness strobing, chromatic aberration, gaussian-blur bloom, vertical 720×1280 by default.

### Usage

```bash
# Schedule = [{"clip_path": "...", "trim_start": 0.2, "duration": 2.0}, ...]
cat > schedule.json <<'EOF'
[
  {"clip_path": "01_neon_grid.mp4",        "trim_start": 0.2, "duration": 2.0},
  {"clip_path": "02_wireframe.mp4",        "trim_start": 0.5, "duration": 1.0},
  {"clip_path": "03_fractal_squares.mp4",  "trim_start": 0.3, "duration": 2.0}
]
EOF

python scripts/dmt_flash_editor.py \
    --schedule schedule.json \
    --audio song.flac \
    --output dmt_flash.mp4 \
    --width 720 --height 1280 --fps 24 \
    --brightness-peak 0.7 \
    --hue-deg 60 \
    --lufs -12.0
```

### What it does

1. Loads schedule + audio
2. Detects beats via librosa
3. Builds a hard-cut concat: each clip trimmed to its specified duration, no crossfades
4. Wraps the cut video in:
   - **Per-beat brightness flash** (`eq` driven by sendcmd, +0.7 on each beat, decay over 60 ms)
   - **Hue rotation** by spectral centroid (`hue h=...` driven dynamically)
   - **Chromatic aberration**: `rgbashift rh=+4, bh=-4` (constant, gives the "DMT pixel-shift" feel)
   - **Bloom**: `gblur σ=8` of input + `blend=screen` over original (subtle glow on bright pixels)
   - Optional `showcqt` (spectrum analyzer overlay) + `avectorscope` (stereo lissajous)
5. Final loudnorm to target LUFS (default −12 for EDM)

Total typical render: ~30–60 s for a 16 s output on a modest CPU.

### Tuning

```bash
# Tame the strobing
--brightness-peak 0.3   # default 0.7

# Less hue rotation (more naturalistic colors)
--hue-deg 30            # default 60

# Disable individual effects
--no-chromatic
--no-bloom
--no-cqt
--no-vectorscope
```

## Companion workflow with aeon-music-maker

The natural pipeline is:

1. **Generate the song** with `aeon-music-maker` (see that repo's SKILL.md):
   ```bash
   python music_maker.py --prompt "psychedelic trance ..." --duration 90 \
       --bpm 140 --key "F minor" --variant xl_base --master edm \
       -o my_track.flac
   ```
2. **Generate or curate clips** — any video source works (LTX-rendered, stock footage, your own clips)
3. **Build the music video** with `reactive_compositor.py` (smooth) or `dmt_flash_editor.py` (hard-cut)

`aeon-movie-maker` can render the source clips for step 2 — see that repo for the LTX 2.3 22B fast cinematic pipeline.

## Failure modes

| Symptom | Fix |
|---|---|
| Video freezes after ~20 s | The `loop` filter has a known stall — these scripts use `-stream_loop -1` at the demuxer level instead, which fixes it |
| `sendcmd` errors with "Missing separator" | sendcmd file syntax is `TIME TARGET PARAM VALUE` (no brackets, no "command" keyword); the scripts handle this — only happens if you hand-edit the sendcmd file |
| Brightness pulses look stepped | Lower `--brightness-peak` to make individual flashes shorter, or raise the audio's beat-detection sensitivity |
| Output is too dark / washed out | Adjust the `eq` baseline values in the script source — the defaults are tuned for vibrant DMT/EDM aesthetics, less appropriate for natural footage |

## See also

- [`aeon-music-maker`](https://github.com/AEON-7/aeon-music-maker) — generate the audio
- [`aeon-movie-maker`](https://github.com/AEON-7/aeon-movie-maker) — generate the source video clips via LTX 2.3
- [`aeon-radio-drama`](https://github.com/AEON-7/aeon-radio-drama) — narrative audio
