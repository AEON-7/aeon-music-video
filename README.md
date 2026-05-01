# aeon-music-video


[![☕ Tips](https://img.shields.io/badge/%E2%98%95_Tips-Support_the_work-ff5e5b?style=flat)](https://github.com/AEON-7/AEON-7#-support-the-work)
> Build audio-reactive music videos from existing video clips and an audio track. Two scripts: `reactive_compositor.py` (smooth mood-driven editing) and `dmt_flash_editor.py` (rapid hard-cut DMT/Tron aesthetic). Both detect beats / onsets / RMS / spectral centroid via librosa and drive ffmpeg filter chains that pulse brightness, hue, zoom, and chromatic aberration in sync with the music.

Part of the **AEON Media Production** family.

## What this gives you

- **Audio analysis-driven editing** — clips are matched to song segments by mood (intensity + brightness curves)
- **Beat-synchronized post-processing** — brightness flashes on every kick, hue rotates with spectral centroid, zoom pulses on RMS peaks
- **Hard-cut DMT mode** — `dmt_flash_editor.py` builds 16 s rapid-cut vertical videos with chromatic aberration + gaussian-blur bloom, ideal for short-form social posts
- **Two render modes** — smooth (mood-bucketed crossfades) or hard-cut (no crossfades, every beat is a strobe)
- **No ML required at runtime** — everything is librosa + ffmpeg. The video clips themselves can be from anywhere (LTX, stock, your camera). Pure orchestration.

## Quick start

```bash
git clone https://github.com/AEON-7/aeon-music-video.git
cd aeon-music-video
cp .env.example .env
./setup.sh

# Smooth music video, mood-driven
python scripts/reactive_compositor.py \
    --audio song.flac \
    --mood-clip calm:cosmic.mp4 \
    --mood-clip building:wireframe.mp4 \
    --mood-clip explosive:fractal.mp4 \
    -o music_video.mp4

# DMT-flash hard-cut, vertical
echo '[
  {"clip_path": "clip_01.mp4", "trim_start": 0.2, "duration": 2.0},
  {"clip_path": "clip_02.mp4", "trim_start": 0.5, "duration": 1.0}
]' > schedule.json
python scripts/dmt_flash_editor.py \
    --schedule schedule.json \
    --audio song.flac \
    -o dmt_flash.mp4
```

See `SKILL.md` for the full guide: mood buckets, parameter tuning, companion workflow with `aeon-music-maker` for the audio side and `aeon-movie-maker` for the source clips.

## Prerequisites

- Python 3.10+ with librosa, numpy, scipy, soundfile (handled by `requirements.txt`)
- ffmpeg + ffprobe on PATH (any modern build with `sendcmd`, `eq`, `hue`, `rgbashift`, `gblur`, `showcqt`, `avectorscope`)
- Source video clips (any format ffmpeg reads)
- An audio track (FLAC / WAV / MP3)

No ComfyUI required. No GPU required. Pure CPU pipeline.

## Project structure

```
aeon-music-video/
├── README.md
├── AGENTS.md
├── SKILL.md          full guide: when to use which script, mood buckets, tuning
├── ATTRIBUTION.md
├── LICENSE
├── .env.example
├── .gitignore
├── setup.sh
├── sync.sh
├── requirements.txt
└── scripts/
    ├── reactive_compositor.py   smooth mood-driven editor
    └── dmt_flash_editor.py      hard-cut rapid editor
```

## License

MIT.

## See also

- [`aeon-music-maker`](https://github.com/AEON-7/aeon-music-maker) — generate the audio
- [`aeon-movie-maker`](https://github.com/AEON-7/aeon-movie-maker) — generate source clips via LTX 2.3
- [`aeon-radio-drama`](https://github.com/AEON-7/aeon-radio-drama) — narrative audio production
- [`comfyui-aeon-spark`](https://github.com/AEON-7/comfyui-aeon-spark) — base ComfyUI Docker stack

---

## ☕ Support the work

If this release has been useful, tips are deeply appreciated — they go directly toward more compute, more models, and more open releases.

<table align="center">
  <tr>
    <td align="center" width="50%">
      <strong>₿ Bitcoin (BTC)</strong><br/>
      <img src="https://raw.githubusercontent.com/AEON-7/AEON-7/main/assets/qr/btc.png" alt="BTC QR" width="200"/><br/>
      <sub><code>bc1q09xmzn00q4z3c5raene0f3pzn9d9pvawfm0py4</code></sub>
    </td>
    <td align="center" width="50%">
      <strong>Ξ Ethereum (ETH)</strong><br/>
      <img src="https://raw.githubusercontent.com/AEON-7/AEON-7/main/assets/qr/eth.png" alt="ETH QR" width="200"/><br/>
      <sub><code>0x1512667F6D61454ad531d2E45C0a5d1fd82D0500</code></sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%">
      <strong>◎ Solana (SOL)</strong><br/>
      <img src="https://raw.githubusercontent.com/AEON-7/AEON-7/main/assets/qr/sol.png" alt="SOL QR" width="200"/><br/>
      <sub><code>DgQsjHdAnT5PNLQTNpJdpLS3tYGpVcsHQCkpoiAKsw8t</code></sub>
    </td>
    <td align="center" width="50%">
      <strong>ⓜ Monero (XMR)</strong><br/>
      <img src="https://raw.githubusercontent.com/AEON-7/AEON-7/main/assets/qr/xmr.png" alt="XMR QR" width="200"/><br/>
      <sub><code>836XrSKw4R76vNi3QPJ5Fa9ugcyvE2cWmKSPv3AhpTNNKvqP8v5ba9JRL4Vh7UnFNjDz3E2GXZDVVenu3rkZaNdUFhjAvgd</code></sub>
    </td>
  </tr>
</table>

> **Ethereum L2s (Base, Arbitrum, Optimism, Polygon, etc.) and EVM-compatible tokens** can be sent to the same Ethereum address.
