#!/usr/bin/env python3
"""DMT Flash Editor — hyper-kinetic rapid-cut music video compositor.

Different from reactive_compositor.py in that it:
  - Uses HARD CUTS (no xfade) on a beat-locked grid
  - Trims each scene clip to a pre-specified short duration (1–2 s)
  - Applies AGGRESSIVE reactive post-processing:
      * brightness pulses up to 0.7 (vs 0.35 elsewhere)
      * hue rotations ±60° (vs ±45°)
      * chromatic aberration via rgbashift (red/blue channel offset pumping with beat)
      * bloom / glow via duplicate + gblur + screen blend
  - Vertical aspect output (720×1280 default)
  - Louder loudnorm target (−12 LUFS for EDM / aggressive)

Input: a schedule listing (clip_path, trim_start, duration) in playback order,
plus an audio track. Output: the final MP4.
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


def analyze_audio_for_flash(audio_path, fps=24):
    """Like reactive_compositor.analyze_audio but tuned for high-energy cuts."""
    y, sr = librosa.load(audio_path, sr=None, mono=True)
    dur = len(y) / sr
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    hop = max(1, sr // fps)
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    e_min, e_max = onset_env.min(), onset_env.max()
    rng = (e_max - e_min) if e_max > e_min else 1.0
    onset_norm = (onset_env - e_min) / rng
    onset_norm = np.power(onset_norm, 0.6)  # stronger response curve

    cent = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=hop)[0]
    c_min, c_max = 80.0, 10000.0
    cent_norm = np.clip((cent - c_min) / (c_max - c_min), 0.0, 1.0)

    return {
        "duration":   dur,
        "sr":         sr,
        "fps":        fps,
        "tempo":      float(tempo) if np.isscalar(tempo) else float(tempo.item()),
        "beat_times": beat_times.tolist(),
        "onset_env":  onset_norm.tolist(),
        "centroid":   cent_norm.tolist(),
    }


def build_aggressive_beat_commands(beat_times, param, peak, baseline, decay_s, fps, min_delta=0.02):
    """Like reactive_compositor's beat pulse but sharper (faster decay, higher peak)."""
    commands = []
    beats = np.asarray(beat_times)
    if beats.size == 0:
        return [(0.0, param, baseline)]
    t_end = beats[-1] + 0.5
    t = 0.0
    step = 1.0 / fps
    last = None
    while t <= t_end:
        prior = beats[beats <= t]
        if prior.size == 0:
            v = baseline
        else:
            dt = t - prior[-1]
            v = baseline + peak * np.exp(-dt / decay_s)
        if last is None or abs(v - last) > min_delta:
            commands.append((t, param, v))
            last = v
        t += step
    return commands


def build_hue_commands(centroid, param, min_deg, max_deg, min_delta, fps):
    commands = []
    last = None
    for i, c in enumerate(centroid):
        t = i / fps
        v = min_deg + (max_deg - min_deg) * float(c)
        if last is None or abs(v - last) > min_delta:
            commands.append((t, param, v))
            last = v
    return commands


def build_dmt_video(schedule, audio_path, out_path, *,
                    width=720, height=1280, fps=24,
                    brightness_peak=0.7, hue_deg=60.0,
                    chromatic_aberration=True, bloom=True,
                    loudnorm_i=-12.0, cqt_overlay=True, vectorscope_overlay=True):
    """Build the DMT flash video.

    `schedule` is a list of dicts:
        [{clip_path, trim_start, duration}, ...]
    Each entry becomes one hard-cut segment in playback order.
    """
    assert schedule, "Need at least one scene in the schedule"

    # Use RELATIVE tmp dir so ffmpeg sendcmd file paths parse cleanly
    tmp_rel = os.path.join("_tmp_dmt", f"r{os.getpid()}_{int(time.time())%100000}")
    os.makedirs(tmp_rel, exist_ok=True)

    print(f"Analyzing audio: {audio_path}")
    analysis = analyze_audio_for_flash(audio_path, fps=fps)
    total_dur = sum(s["duration"] for s in schedule)
    print(f"  audio duration: {analysis['duration']:.1f}s  tempo: {analysis['tempo']:.1f} BPM")
    print(f"  schedule: {len(schedule)} cuts totaling {total_dur:.1f}s  beats: {len(analysis['beat_times'])}")

    # --- Sendcmd files for aggressive reactive effects ---
    bright_cmds = build_aggressive_beat_commands(
        analysis["beat_times"], "brightness", brightness_peak, 0.0, 0.12, fps)
    sat_cmds = [(t, "saturation", 1.0 + 0.8 * e) for i, e in enumerate(analysis["onset_env"])
                for t in [i / fps]]
    # Dedupe saturation for throttling
    sat_commands = []
    last = None
    for t, p, v in sat_cmds:
        if last is None or abs(v - last) > 0.04:
            sat_commands.append((t, p, v))
            last = v
    eq_cmds = sorted(bright_cmds + sat_commands, key=lambda x: x[0])
    eq_file = os.path.join(tmp_rel, "eq.txt")
    with open(eq_file, "w") as f:
        for t, p, v in eq_cmds:
            f.write(f"{t:.4f} myeq {p} {v:.4f};\n")

    hue_cmds = build_hue_commands(analysis["centroid"], "h",
                                   -hue_deg, hue_deg, 1.2, fps)
    hue_file = os.path.join(tmp_rel, "hue.txt")
    with open(hue_file, "w") as f:
        for t, p, v in hue_cmds:
            f.write(f"{t:.4f} myhue {p} {v:.4f};\n")

    print(f"  eq commands: {len(eq_cmds)}  hue commands: {len(hue_cmds)}")

    # --- Build filter graph: trim each scene, scale to vertical, concat ---
    clip_to_input = {}
    for i, s in enumerate(schedule):
        if s["clip_path"] not in clip_to_input:
            clip_to_input[s["clip_path"]] = len(clip_to_input)
    unique_clips = sorted(clip_to_input, key=clip_to_input.get)
    audio_idx = len(unique_clips)

    filter_parts = []
    # Each unique clip: stream-looped at input side; here we just prep it
    for i, p in enumerate(unique_clips):
        filter_parts.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps={fps}[src{i}]"
        )

    # Trim each scene from its assigned clip
    seg_labels = []
    for idx, s in enumerate(schedule):
        src = clip_to_input[s["clip_path"]]
        start = float(s["trim_start"])
        dur = float(s["duration"])
        lbl = f"seg{idx}"
        filter_parts.append(
            f"[src{src}]trim=start={start:.3f}:duration={dur:.3f},"
            f"setpts=PTS-STARTPTS[{lbl}]"
        )
        seg_labels.append(lbl)

    # Concatenate with hard cuts (no xfade)
    concat_in = "".join(f"[{l}]" for l in seg_labels)
    filter_parts.append(f"{concat_in}concat=n={len(seg_labels)}:v=1:a=0[vcut]")

    # Apply reactive effects: eq (brightness+saturation) + hue, both sendcmd-driven
    eq_fg = eq_file.replace("\\", "/")
    hue_fg = hue_file.replace("\\", "/")
    filter_parts.append(
        f"[vcut]sendcmd=f={eq_fg},eq@myeq=brightness=0:saturation=1,"
        f"sendcmd=f={hue_fg},hue@myhue=h=0:s=1[vreact]"
    )
    cur = "vreact"

    # Chromatic aberration (RGB channel shift pumping with intensity)
    if chromatic_aberration:
        # rgbashift: r_h shifts red horizontally, b_h shifts blue; static values
        # for simplicity (dynamic would need per-frame sendcmd, overkill here)
        filter_parts.append(
            f"[{cur}]rgbashift=rh=4:bh=-4:rv=0:bv=0[vchrom]"
        )
        cur = "vchrom"

    # Bloom glow: duplicate, heavy-blur the copy, screen-blend back
    if bloom:
        filter_parts.append(f"[{cur}]split=2[vclean][vsoft]")
        filter_parts.append(f"[vsoft]gblur=sigma=8[vbloom]")
        filter_parts.append(f"[vclean][vbloom]blend=all_mode=screen:all_opacity=0.35[vbloomed]")
        cur = "vbloomed"

    # Audio-viz overlays
    if cqt_overlay:
        filter_parts.append(
            f"[{audio_idx}:a]showcqt=s={width}x80:bar_h=60:axis_h=0:sono_h=20:"
            f"count=3:fps={fps}:cscheme=0.9|0|1|1|0.4|0.7:bar_g=4:sono_g=5:bar_t=0.2,"
            f"format=yuva420p,colorchannelmixer=aa=0.75[cqt]"
        )
        filter_parts.append(f"[{cur}][cqt]overlay=x=0:y=H-h:shortest=1[vcqt]")
        cur = "vcqt"
    if vectorscope_overlay:
        filter_parts.append(
            f"[{audio_idx}:a]avectorscope=s=160x160:rf=255:gf=100:bf=200:"
            f"scale=sqrt:draw=line:zoom=1.5:rate={fps},format=yuva420p,"
            f"colorchannelmixer=aa=0.65[vec]"
        )
        filter_parts.append(f"[{cur}][vec]overlay=x=W-w-12:y=12[vfinal]")
        cur = "vfinal"

    filter_complex = ";".join(filter_parts)

    cmd = [FFMPEG, "-y"]
    for p in unique_clips:
        cmd += ["-stream_loop", "-1", "-i", p]
    cmd += ["-i", audio_path,
            "-filter_complex", filter_complex,
            "-map", f"[{cur}]", "-map", f"{audio_idx}:a",
            "-c:v", "libx264", "-crf", "18", "-preset", "medium",
            "-pix_fmt", "yuv420p",
            "-af", f"loudnorm=I={loudnorm_i}:TP=-0.5:LRA=5",
            "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
            "-t", f"{total_dur:.3f}",   # exact duration (schedule-driven)
            out_path]

    print(f"\nrunning ffmpeg...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("STDERR tail:")
        print(r.stderr[-3000:])
        # Dump filter for debugging
        fc_file = os.path.join(tmp_rel, "filter_complex.txt")
        with open(fc_file, "w") as f:
            f.write(filter_complex)
        print(f"filter_complex dumped to: {fc_file}")
        raise RuntimeError("ffmpeg failed")

    dur = probe_duration(out_path)
    size_mb = os.path.getsize(out_path) / 1024 / 1024
    print(f"\n=== OUTPUT ===")
    print(f"  file: {out_path}")
    print(f"  duration: {dur:.2f}s  ({width}x{height})")
    print(f"  size: {size_mb:.1f} MB")
    print(f"  loudness: {loudnorm_i} LUFS")
    return out_path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--schedule", required=True,
                   help="JSON file with a list of {clip_path, trim_start, duration} entries")
    p.add_argument("--audio", required=True)
    p.add_argument("--output", "-o", required=True)
    p.add_argument("--width", type=int, default=720)
    p.add_argument("--height", type=int, default=1280)
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--brightness-peak", type=float, default=0.7)
    p.add_argument("--hue-deg", type=float, default=60.0)
    p.add_argument("--no-chromatic", action="store_false", dest="chromatic_aberration", default=True)
    p.add_argument("--no-bloom", action="store_false", dest="bloom", default=True)
    p.add_argument("--no-cqt", action="store_false", dest="cqt_overlay", default=True)
    p.add_argument("--no-vectorscope", action="store_false", dest="vectorscope_overlay", default=True)
    p.add_argument("--lufs", type=float, default=-12.0)
    args = p.parse_args()

    with open(args.schedule) as f:
        schedule = json.load(f)

    build_dmt_video(schedule, args.audio, args.output,
                     width=args.width, height=args.height, fps=args.fps,
                     brightness_peak=args.brightness_peak, hue_deg=args.hue_deg,
                     chromatic_aberration=args.chromatic_aberration,
                     bloom=args.bloom,
                     cqt_overlay=args.cqt_overlay,
                     vectorscope_overlay=args.vectorscope_overlay,
                     loudnorm_i=args.lufs)


if __name__ == "__main__":
    main()
