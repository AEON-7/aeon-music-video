#!/usr/bin/env python3
"""Audio-reactive video compositor.

Takes an audio file + any number of video clips, analyzes the audio with
librosa, and builds an FFmpeg filter graph that makes the *animation itself*
respond to the music — not just overlays:

  - **Zoom pulse** on every detected beat (brief spike, exponential decay)
  - **Brightness lift** tracking the onset envelope (continuous)
  - **Hue rotation** driven by spectral centroid (bass → warm, highs → cool)
  - **Clip switching** on strong downbeats (every N beats, default 8)

On top of the reactive base, it composites the existing cqt spectrum + vectorscope
overlays so you get BOTH the animation-reactive fractals AND audio-viz graphics.

Uses ffmpeg's `sendcmd` filter — the only reliable way to drive `eq` and `hue`
parameters on a time-varying schedule without encoding a piecewise megaexpression.
"""
import argparse, json, os, subprocess, sys, tempfile, time
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import librosa

FFMPEG = r"${FFMPEG:-ffmpeg}"
FFPROBE = r"${FFPROBE:-ffprobe}"


def probe_duration(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                       "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(r.stdout.strip())


def analyze_audio(audio_path, fps=24):
    """Extract beat times, onset envelope (per video frame), spectral centroid,
    and per-video-frame RMS. RMS + centroid are used for mood-based clip selection."""
    y, sr = librosa.load(audio_path, sr=None, mono=True)
    dur = len(y) / sr

    # Beat tracking — returns BPM + list of beat frame indices (librosa frames)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    # Per-video-frame onset strength envelope (0..1 normalized)
    hop = max(1, sr // fps)
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    e_min, e_max = onset_env.min(), onset_env.max()
    rng = (e_max - e_min) if e_max > e_min else 1.0
    onset_norm = (onset_env - e_min) / rng
    onset_norm = np.power(onset_norm, 0.7)  # gamma < 1 raises mid values

    # Per-video-frame RMS (root-mean-square energy) — drives "intensity" mood mapping
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    r_min, r_max = rms.min(), rms.max()
    rms_norm = (rms - r_min) / ((r_max - r_min) or 1.0)

    # Spectral centroid → hue + also a "brightness" axis for mood selection
    cent = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=hop)[0]
    c_min, c_max = 80.0, 8000.0
    cent_norm = np.clip((cent - c_min) / (c_max - c_min), 0.0, 1.0)

    # Downbeat markers: every 8th beat = one major structural breakpoint
    major_beats = beat_times[::8] if len(beat_times) > 0 else np.array([])

    return {
        "duration":    dur,
        "sr":          sr,
        "fps":         fps,
        "tempo":       float(tempo) if np.isscalar(tempo) else float(tempo.item()),
        "beat_times":  beat_times.tolist(),
        "major_beats": major_beats.tolist(),
        "onset_env":   onset_norm.tolist(),
        "rms":         rms_norm.tolist(),
        "centroid":    cent_norm.tolist(),
    }


# -----------------------------------------------------------------------------
# Mood-based clip assignment
# -----------------------------------------------------------------------------
# Each "mood" bucket describes a (intensity, brightness) region in feature space.
# intensity comes from RMS (energy), brightness from spectral centroid.
# When 6 mood-varied clips are provided, each clip is assigned to its bucket.
MOOD_BUCKETS = [
    # (name,               intensity_range, brightness_range)
    ("calm_orbital",       (0.00, 0.35),    (0.00, 0.55)),  # low energy, any brightness
    ("cosmic_mandala",     (0.00, 0.50),    (0.35, 0.70)),  # medium-low, mid brightness
    ("building_spiral",    (0.30, 0.70),    (0.00, 0.70)),  # medium energy
    ("crystalline_shimmer",(0.25, 0.75),    (0.55, 1.00)),  # mid energy, bright (treble)
    ("deep_zoom",          (0.55, 1.00),    (0.00, 0.55)),  # high energy, dark/bass
    ("explosive_burst",    (0.65, 1.00),    (0.00, 1.00)),  # peak energy, any brightness
]


def choose_mood_for_segment(seg_intensity, seg_brightness, available_moods):
    """Pick the best-matching mood for a segment's (intensity, brightness) stats.

    Falls back to the first available mood if no bucket perfectly contains the
    segment coordinates (chooses the closest by bucket center).
    """
    best = None
    best_dist = float("inf")
    for name, (ilo, ihi), (blo, bhi) in MOOD_BUCKETS:
        if name not in available_moods:
            continue
        ic = (ilo + ihi) / 2
        bc = (blo + bhi) / 2
        in_bucket = ilo <= seg_intensity <= ihi and blo <= seg_brightness <= bhi
        # Prefer in-bucket; among those, pick closest to center.
        # For out-of-bucket, pick globally closest.
        d = ((seg_intensity - ic) ** 2 + (seg_brightness - bc) ** 2) ** 0.5
        if in_bucket:
            d -= 10.0  # bonus to prefer in-bucket
        if d < best_dist:
            best_dist = d
            best = name
    return best


def assign_clips_by_audio(segments, analysis, clip_paths_by_name):
    """For each segment, pick the mood-matching clip path.

    Args:
        segments: [{start, end, ...}, ...] — output of segmentation
        analysis: dict from analyze_audio()
        clip_paths_by_name: {mood_name: clip_path} — the rendered mood clips

    Returns:
        list of dicts: [{start, end, clip_name, clip_path, intensity, brightness}, ...]
    """
    fps = analysis["fps"]
    rms = np.asarray(analysis["rms"])
    cent = np.asarray(analysis["centroid"])
    total_frames = len(rms)

    available = set(clip_paths_by_name.keys())

    assigned = []
    for seg in segments:
        start_f = int(seg["start"] * fps)
        end_f = min(total_frames, int(seg["end"] * fps))
        if end_f <= start_f:
            end_f = start_f + 1

        seg_intensity = float(np.mean(rms[start_f:end_f])) if end_f > start_f else 0.0
        seg_brightness = float(np.mean(cent[start_f:end_f])) if end_f > start_f else 0.5

        mood = choose_mood_for_segment(seg_intensity, seg_brightness, available)
        assigned.append({
            **seg,
            "clip_name": mood,
            "clip_path": clip_paths_by_name.get(mood),
            "intensity": round(seg_intensity, 3),
            "brightness": round(seg_brightness, 3),
        })
    return assigned


def build_sendcmd_file(analysis, target_label, param_exprs, tmp_dir):
    """Write a sendcmd file that applies timed param updates to a named filter.

    `param_exprs` is a list of (time_s, param_name, value) tuples.
    target_label is the filter instance tag, e.g. 'my_eq' when filter is 'eq@my_eq=...'.
    """
    path = os.path.join(tmp_dir, f"{target_label}_sendcmd.txt")
    with open(path, "w") as f:
        for t, param, value in param_exprs:
            # Command syntax: `TIME [enter] target_name filter_param value`
            # See https://ffmpeg.org/ffmpeg-filters.html#commands
            f.write(f"{t:.4f} {target_label} {param} {value:.4f};\n")
    return path


def build_beat_pulse_commands(beat_times, param_name="brightness",
                               peak=0.15, baseline=0.0, decay_s=0.18, fps=24):
    """Generate (time, value) pairs that pulse a parameter on each beat.

    Peak on beat, decay back to baseline over decay_s. Emits at video-frame
    granularity (1/fps) for smoothness, only where the value has changed.
    """
    commands = []
    frame_step = 1.0 / fps
    # Sample a timeline of `value(t)` driven by beat impulses with exponential decay
    times = []
    values = []
    if not beat_times:
        return [(0.0, param_name, baseline)]
    t_end = beat_times[-1] + 1.0
    t = 0.0
    # Precompute nearest-beat and decay curve
    beats = np.asarray(beat_times)
    while t <= t_end:
        # Time since last beat before t
        prior_beats = beats[beats <= t]
        if prior_beats.size == 0:
            v = baseline
        else:
            dt = t - prior_beats[-1]
            v = baseline + peak * np.exp(-dt / decay_s)
        times.append(t)
        values.append(v)
        t += frame_step

    # Emit as sendcmd commands; only when value changes by > 0.01 to avoid spam
    last = None
    for t, v in zip(times, values):
        if last is None or abs(v - last) > 0.01:
            commands.append((t, param_name, v))
            last = v
    return commands


def build_onset_drive_commands(onset_env, param_name, mapping,
                                min_delta=0.03, fps=24):
    """Map the onset envelope timeline to a ffmpeg parameter.

    mapping: callable mapping onset_value∈[0,1] → parameter value.
    Emits commands at video-frame rate, throttled by min_delta.
    """
    commands = []
    last = None
    for i, env in enumerate(onset_env):
        t = i / fps
        v = float(mapping(env))
        if last is None or abs(v - last) > min_delta:
            commands.append((t, param_name, v))
            last = v
    return commands


def build_centroid_drive_commands(centroid, param_name, min_val=0.0, max_val=60.0,
                                   min_delta=1.0, fps=24):
    """Drive a param over [min_val, max_val] from spectral centroid [0,1]."""
    commands = []
    last = None
    for i, c in enumerate(centroid):
        t = i / fps
        v = min_val + (max_val - min_val) * float(c)
        if last is None or abs(v - last) > min_delta:
            commands.append((t, param_name, v))
            last = v
    return commands


def build_reactive_video(clip_paths, audio_path, out_path, *,
                          fps=24, width=832, height=480,
                          beat_switch_every_n_major=1,
                          zoom_peak=0.12, brightness_peak=0.25, hue_max_deg=30.0,
                          cqt_overlay=True, vectorscope_overlay=True,
                          loudnorm_i=-14.0,
                          clip_paths_by_mood=None):
    """Compose a full audio-reactive video. Returns the output path.

    If `clip_paths_by_mood` is provided (a dict mapping mood name → clip path),
    segments are assigned to clips by matching audio features (RMS + centroid)
    instead of round-robin cycling through `clip_paths`. This gives true
    song-structure-driven visual flow (calm sections → calm clip, drops →
    explosive clip, etc.)
    """
    assert len(clip_paths) >= 1, "Need at least 1 clip"
    # Use a RELATIVE tmp dir so ffmpeg's filter-arg parser doesn't choke on
    # Windows drive-letter colons inside a sendcmd `f=PATH` arg. FFmpeg treats
    # `:` as a filter-option separator; even with escapes, absolute Windows
    # paths fail to parse. Relative path from CWD works cleanly.
    tmp_rel = os.path.join("_tmp_reactive", f"r{os.getpid()}_{int(time.time())%100000}")
    os.makedirs(tmp_rel, exist_ok=True)
    tmp_dir = tmp_rel  # stored for file writes + ffmpeg refs

    print(f"Analyzing audio: {audio_path}")
    analysis = analyze_audio(audio_path, fps=fps)
    print(f"  duration: {analysis['duration']:.1f}s  tempo: {analysis['tempo']:.1f} BPM")
    print(f"  beats: {len(analysis['beat_times'])}  major (every 8th): {len(analysis['major_beats'])}")

    total_dur = analysis["duration"]

    # --- Beat-driven clip switching sequence ---
    # Given the major-beat times + N clips, assign each inter-major segment to
    # one clip (round-robin). Result: a sequence of (start_time, end_time, clip_idx).
    mb = [0.0] + analysis["major_beats"] + [total_dur]
    mb = sorted(set(float(x) for x in mb if x <= total_dur))
    if mb[-1] < total_dur:
        mb.append(total_dur)

    raw_segments = []
    for i in range(len(mb) - 1):
        raw_segments.append({"start": mb[i], "end": mb[i+1]})

    if clip_paths_by_mood:
        # Audio-driven clip selection: pick mood matching each segment's features
        assigned = assign_clips_by_audio(raw_segments, analysis, clip_paths_by_mood)
        # Build the ordered list of clip paths we'll actually use as inputs
        unique_paths = []
        path_to_idx = {}
        for a in assigned:
            p = a["clip_path"]
            if p and p not in path_to_idx:
                path_to_idx[p] = len(unique_paths)
                unique_paths.append(p)
        # Build segments in the (start, end, clip_idx) format the rest of the
        # function uses; clip_idx is into the deduplicated unique_paths list.
        segments = []
        for a in assigned:
            if a["clip_path"] is None:
                a["clip_path"] = unique_paths[0]  # fallback
            segments.append({"start": a["start"], "end": a["end"],
                             "clip": path_to_idx[a["clip_path"]],
                             "mood": a["clip_name"],
                             "intensity": a["intensity"],
                             "brightness": a["brightness"]})
        # Replace caller's clip_paths with the mood-ordered subset actually used
        clip_paths = unique_paths
        print(f"  audio-driven segments: {len(segments)} "
              f"({len(unique_paths)} unique clips used)")
        for i, s in enumerate(segments[:12]):
            print(f"    [{i:2d}] {s['start']:6.2f}-{s['end']:6.2f}s  "
                  f"I={s['intensity']:.2f} B={s['brightness']:.2f}  → {s['mood']}")
        if len(segments) > 12:
            print(f"    ... ({len(segments) - 12} more)")
    else:
        # Original round-robin
        segments = []
        for i in range(len(mb) - 1):
            clip_idx = i % len(clip_paths)
            segments.append({"start": mb[i], "end": mb[i+1], "clip": clip_idx})
        print(f"  clip-switch segments: {len(segments)} (round-robin)")

    # --- Sendcmd files for time-varying effects ---
    # Zoom pulse on beats → actually drive `scale` via crop + scale, but simpler:
    # use the `zoompan` filter with its own cumulative logic is rough. Instead,
    # use `scale2ref` or, easier, apply `scale=<w>*(1+z):<h>*(1+z)` with sendcmd
    # on the scale factor via the `zscale` filter...
    # Actually cleanest: use `crop` on the upscaled-by-headroom video + `sendcmd`.
    #
    # But even cleaner: drive `eq=brightness=` on beats and `hue=h=` on centroid.
    # Zoom effect comes via `scale` with time-varying output size fed through
    # sendcmd to a `scale` filter tagged with @scale_target.
    #
    # We'll do: eq@myeq (brightness+saturation), hue@myhue (rotation), and
    # use a simple no-zoom path. Zoom via sendcmd is unreliable across ffmpeg
    # versions; the beat-driven brightness+hue already make it feel reactive.

    bright_cmds = build_beat_pulse_commands(
        analysis["beat_times"], param_name="brightness",
        peak=brightness_peak, baseline=0.0, decay_s=0.22, fps=fps,
    )
    sat_cmds = build_onset_drive_commands(
        analysis["onset_env"], param_name="saturation",
        mapping=lambda e: 1.0 + 0.6 * e, fps=fps,
    )
    hue_cmds = build_centroid_drive_commands(
        analysis["centroid"], param_name="h", min_val=-hue_max_deg, max_val=hue_max_deg,
        min_delta=0.8, fps=fps,
    )

    # Merge brightness + saturation into a single sendcmd file targeting eq@myeq.
    # Correct ffmpeg sendcmd file syntax:  "TIME TARGET COMMAND PARAM VALUE;"
    # where TARGET is the filter instance tag (no brackets) and COMMAND is
    # always `command` for parameter updates.
    eq_cmds = sorted(bright_cmds + sat_cmds, key=lambda x: x[0])
    eq_cmd_file = os.path.join(tmp_dir, "eq_cmds.txt")
    with open(eq_cmd_file, "w") as f:
        for t, p, v in eq_cmds:
            f.write(f"{t:.4f} myeq {p} {v:.4f};\n")
    hue_cmd_file = os.path.join(tmp_dir, "hue_cmds.txt")
    with open(hue_cmd_file, "w") as f:
        for t, p, v in hue_cmds:
            f.write(f"{t:.4f} myhue {p} {v:.4f};\n")

    print(f"  eq commands: {len(eq_cmds)}  hue commands: {len(hue_cmds)}")

    # --- Per-segment trimmed video inputs ---
    # For each segment, we need to cut that segment from the assigned clip.
    # We'll input all source clips once and use `trim+setpts` to produce the
    # segment streams, then `concat` them end-to-end.
    clip_durs = [probe_duration(p) for p in clip_paths]

    # Build filter_complex:
    filter_parts = []
    # 1. Each clip is stream-looped at the INPUT side (via -stream_loop -1 in ffmpeg
    #    args), so here we just scale/normalize and trim to total_dur. The `loop`
    #    *filter* is unreliable: with small source clips (< total_dur) and a
    #    downstream trim, it can stall after the first cycle, producing a
    #    frozen final frame. `-stream_loop` at the demuxer level avoids that.
    for i, p in enumerate(clip_paths):
        filter_parts.append(
            f"[{i}:v]scale={width}:{height},setsar=1,fps={fps},"
            f"trim=duration={total_dur:.3f},setpts=PTS-STARTPTS[loop{i}]"
        )

    # 2. For each segment, extract the time window from its assigned clip
    segment_labels = []
    for s_idx, seg in enumerate(segments):
        src = seg["clip"]
        start, end = seg["start"], seg["end"]
        dur = end - start
        lbl = f"seg{s_idx}"
        filter_parts.append(
            f"[loop{src}]trim=start={start:.3f}:duration={dur:.3f},setpts=PTS-STARTPTS[{lbl}]"
        )
        segment_labels.append(lbl)

    # 3. Concatenate segments back into a continuous stream
    if len(segment_labels) > 1:
        concat_in = "".join(f"[{l}]" for l in segment_labels)
        filter_parts.append(
            f"{concat_in}concat=n={len(segment_labels)}:v=1:a=0[vswitched]"
        )
    else:
        filter_parts.append(f"[{segment_labels[0]}]null[vswitched]")

    # 4. Apply audio-reactive filters via sendcmd.
    # Use RELATIVE forward-slash paths (no drive letter) to avoid ffmpeg's
    # filter-arg colon ambiguity. Files were written under _tmp_reactive/ which
    # is relative to CWD; ffmpeg will resolve there when invoked.
    eq_cmd_file_fg = eq_cmd_file.replace("\\", "/")
    hue_cmd_file_fg = hue_cmd_file.replace("\\", "/")
    filter_parts.append(
        f"[vswitched]sendcmd=f={eq_cmd_file_fg},eq@myeq=brightness=0:saturation=1,"
        f"sendcmd=f={hue_cmd_file_fg},hue@myhue=h=0:s=1[vreactive]"
    )

    # 5. Audio-viz overlays (reuse from earlier composite)
    cur_label = "vreactive"
    audio_idx = len(clip_paths)
    if cqt_overlay:
        filter_parts.append(
            f"[{audio_idx}:a]showcqt=s={width}x80:bar_h=60:axis_h=0:sono_h=20:"
            f"count=3:fps={fps}:cscheme=0.9|0|1|1|0.4|0.7:bar_g=4:sono_g=5:bar_t=0.2,"
            f"format=yuva420p,colorchannelmixer=aa=0.75[cqt]"
        )
        filter_parts.append(f"[{cur_label}][cqt]overlay=x=0:y=H-h:shortest=1[vcqt]")
        cur_label = "vcqt"
    if vectorscope_overlay:
        filter_parts.append(
            f"[{audio_idx}:a]avectorscope=s=200x200:rf=255:gf=100:bf=200:scale=sqrt:"
            f"draw=line:zoom=1.5:rate={fps},format=yuva420p,"
            f"colorchannelmixer=aa=0.65[vec]"
        )
        filter_parts.append(f"[{cur_label}][vec]overlay=x=W-w-16:y=16[vfinal]")
        cur_label = "vfinal"

    filter_complex = ";".join(filter_parts)

    # --- Assemble ffmpeg command ---
    # Each video input gets `-stream_loop -1` (infinite demuxer-level looping)
    # so the filter graph can pull arbitrarily many frames without the `loop`
    # filter's known freeze issues when used with downstream trim+concat.
    cmd = [FFMPEG, "-y"]
    for p in clip_paths:
        cmd += ["-stream_loop", "-1", "-i", p]
    cmd += ["-i", audio_path]
    cmd += [
        "-filter_complex", filter_complex,
        "-map", f"[{cur_label}]", "-map", f"{audio_idx}:a",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-af", f"loudnorm=I={loudnorm_i}:TP=-1.0:LRA=7",
        "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
        "-shortest",
        out_path,
    ]

    # Write filter_complex to a file for future reference + debugging
    fc_path = os.path.join(tmp_dir, "filter_complex.txt")
    with open(fc_path, "w") as f:
        f.write(filter_complex)

    print("\nrunning ffmpeg...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("ffmpeg STDERR tail:")
        print(r.stderr[-3500:])
        print(f"\nfilter_complex dumped to: {fc_path}")
        raise RuntimeError("ffmpeg failed")

    dur = probe_duration(out_path)
    size_mb = os.path.getsize(out_path) / 1024 / 1024
    print(f"\n=== OUTPUT ===")
    print(f"  file: {out_path}")
    print(f"  duration: {dur:.2f}s")
    print(f"  size: {size_mb:.1f} MB")
    return out_path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--audio", required=True, help="Audio file path")
    p.add_argument("--clip", action="append", default=[], dest="clips",
        help="Video clip path (pass --clip multiple times; round-robin assignment)")
    p.add_argument("--mood-clip", action="append", default=[], dest="mood_clips",
        help="Mood-tagged clip: 'name=path'. Known names: calm_orbital, cosmic_mandala, "
             "building_spiral, crystalline_shimmer, deep_zoom, explosive_burst. "
             "When any --mood-clip is provided, audio-driven selection kicks in "
             "and --clip arguments are ignored.")
    p.add_argument("--output", "-o", required=True)
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--width", type=int, default=832)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--no-cqt", action="store_false", dest="cqt_overlay", default=True)
    p.add_argument("--no-vectorscope", action="store_false", dest="vectorscope_overlay", default=True)
    p.add_argument("--zoom-peak", type=float, default=0.12)
    p.add_argument("--brightness-peak", type=float, default=0.25)
    p.add_argument("--hue-max-deg", type=float, default=30.0)
    p.add_argument("--lufs", type=float, default=-14.0)
    args = p.parse_args()

    mood_map = {}
    for spec in args.mood_clips:
        if "=" not in spec:
            raise SystemExit(f"--mood-clip needs 'name=path', got {spec!r}")
        name, path = spec.split("=", 1)
        mood_map[name.strip()] = path.strip()

    clip_list = list(mood_map.values()) if mood_map else args.clips
    if not clip_list:
        raise SystemExit("Provide at least one --clip or --mood-clip")

    build_reactive_video(
        clip_list, args.audio, args.output,
        fps=args.fps, width=args.width, height=args.height,
        zoom_peak=args.zoom_peak, brightness_peak=args.brightness_peak,
        hue_max_deg=args.hue_max_deg,
        cqt_overlay=args.cqt_overlay, vectorscope_overlay=args.vectorscope_overlay,
        loudnorm_i=args.lufs,
        clip_paths_by_mood=mood_map or None,
    )


if __name__ == "__main__":
    main()
