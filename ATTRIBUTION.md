# Attribution

`aeon-music-video` is pure orchestration — librosa for audio analysis, ffmpeg for video composition. No ML models at runtime.

## Python libraries

| Library | Use here | Author |
|---|---|---|
| [librosa](https://github.com/librosa/librosa) | Beat / onset / RMS / spectral-centroid detection that drives all reactive effects | Brian McFee et al. |
| [numpy](https://numpy.org/) / [scipy](https://scipy.org/) | numerical foundation | NumPy / SciPy teams |
| [soundfile](https://github.com/bastibe/python-soundfile) | WAV/FLAC IO | Bastian Bechtold |

## ffmpeg

Every reactive effect runs through [FFmpeg](https://www.ffmpeg.org/) filters:

- `sendcmd` — time-varying parameter control (drives the brightness pulses, hue rotations, zoom, chromatic aberration over the song's timeline)
- `eq` — brightness + saturation
- `hue` — hue rotation
- `rgbashift` — chromatic aberration (DMT mode)
- `gblur` + `blend=screen` — gaussian-blur bloom (DMT mode)
- `showcqt` — spectrum analyzer overlay
- `avectorscope` — stereo Lissajous overlay
- `loudnorm` — final loudness normalization
- `concat` + `crossfade` — clip sequencing

## Pipeline-specific design notes

- **Mood-bucket clip matching**: each clip is assigned to one of six `(intensity, brightness)` ranges (`calm`, `cosmic`, `building`, `crystalline`, `deep`, `explosive`); song segments get matched to a clip whose bucket overlaps the segment's energy curve. Original to this project.
- **Beat-driven sendcmd file generation**: librosa beat times are written into a `sendcmd` text file with `TIME TARGET PARAM VALUE` rows that ffmpeg interprets as time-aligned filter-parameter changes. Avoids needing to render N keyframes manually.
- **DMT-flash post-stack**: `rgbashift rh=+4, bh=-4` (constant chromatic aberration) + `gblur σ=8` of input + `blend=screen` (bloom on bright pixels) — a known recipe in the chiptune/glitch-art aesthetic, codified here.
- **stream_loop fix**: the `loop` filter in ffmpeg has a known stall around 20 s when chained with `trim+concat`. Both scripts use `-stream_loop -1` at the demuxer level instead, which renders cleanly to any duration.

## License notes

This repo is MIT-licensed. ffmpeg is LGPL/GPL depending on build (typically LGPL with the standard distribution). librosa is ISC. All compatible with this MIT release.
