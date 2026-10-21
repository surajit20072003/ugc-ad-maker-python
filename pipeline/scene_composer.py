"""
pipeline/scene_composer.py
──────────────────────────
Scene-level audio/video compositing and timing synchronization.
Key capabilities:
  - Precision muxing of pure Kling B-Roll video with VoxCPM voiceover audio.
  - Trimming, looping, or slowing video to fit measured audio duration down to milliseconds.
  - Ensuring consistent vertical format (720x1280 9:16, 30fps, yuv420p) across all scenes.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

UPLOAD_DIR = Path(__file__).parent.parent / "uploads"


def get_media_duration(file_path: str | Path) -> float:
    """Measure exact duration of an audio or video file using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        try:
            return round(float(res.stdout.strip()), 3)
        except ValueError:
            pass
    return 5.0


def compose_pure_broll_scene(
    video_path: str | Path,
    audio_path: str | Path,
    output_path: str | Path,
    target_duration: Optional[float] = None,
    width: int = 720,
    height: int = 1280,
) -> Path:
    """
    Precision muxing for pure B-roll scenes:
    - Combines Kling video track with VoxCPM speech audio.
    - Synchronizes the video duration precisely to the voiceover length.
    - Rescales / crops cleanly to 9:16 vertical video.
    """
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    # If target duration not provided, get exact duration from audio file
    if target_duration is None or target_duration <= 0:
        target_duration = get_media_duration(audio_path)

    v_dur = get_media_duration(video_path)

    # Build video filter for exact vertical resolution and duration handling
    # Scale to fill 720x1280 (crop if needed), 30fps
    scale_crop_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"fps=30,"
        f"format=yuv420p"
    )

    if v_dur < target_duration:
        # Video is shorter than audio: extend last frame with tpad or loop
        diff = target_duration - v_dur
        v_filter = f"{scale_crop_filter},tpad=stop_mode=clone:stop_duration={diff + 0.1}"
    else:
        # Video is longer than audio: trim to target duration with subtle micro-fade
        v_filter = scale_crop_filter

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-filter_complex", f"[0:v]{v_filter}[v]",
        "-map", "[v]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "19",
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", f"{target_duration:.3f}",
        str(out_p),
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg pure B-roll scene composition failed:\n{res.stderr}")

    return out_p


def standardize_avatar_clip(
    video_path: str | Path,
    output_path: str | Path,
    audio_path: Optional[str | Path] = None,
    width: int = 720,
    height: int = 1280,
) -> Path:
    """
    Normalize avatar lipsync clip to 720x1280 30fps yuv420p with synchronized audio.
    """
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    scale_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"fps=30,"
        f"format=yuv420p"
    )

    cmd = ["ffmpeg", "-y", "-i", str(video_path)]

    if audio_path and os.path.exists(str(audio_path)):
        cmd.extend(["-i", str(audio_path)])
        cmd.extend([
            "-filter_complex", f"[0:v]{scale_filter}[v]",
            "-map", "[v]",
            "-map", "1:a",
        ])
    else:
        cmd.extend([
            "-vf", scale_filter,
            "-c:a", "aac",
        ])

    cmd.extend([
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "19",
        "-c:a", "aac",
        "-b:a", "192k",
        str(out_p),
    ])

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg avatar standardization failed:\n{res.stderr}")

    return out_p


def compose_beat_scene(
    clips: list,
    audio_path: str | Path,
    output_path: str | Path,
    total_duration: float,
    width: int = 720,
    height: int = 1280,
) -> Path:
    """
    Fit several beat clips [(path, target_seconds), ...] to the voiceover and mux the scene WAV.
    Each clip is sped up (up to 1.8x, so the whole start->end animation plays) or slowed (up to 15%) to hit its target; beyond that it is trimmed or end-frame padded.
    """
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["ffmpeg", "-y"]
    parts = []
    for i, (path, target) in enumerate(clips):
        cmd += ["-i", str(path)]
        src = get_media_duration(path)
        target = max(0.5, float(target))
        chain = (
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={width}:{height},setsar=1,fps=30"
        )
        ratio = target / src if src > 0 else 1.0
        if 0.55 <= ratio <= 1.15:
            chain += f",setpts=PTS*{ratio:.5f}"
        elif ratio > 1.15:
            stretched = src * 1.15
            chain += f",setpts=PTS*1.15,tpad=stop_mode=clone:stop_duration={target - stretched + 0.2:.3f}"
        chain += f",trim=duration={target:.3f},setpts=PTS-STARTPTS,format=yuv420p[v{i}]"
        parts.append(chain)

    n = len(clips)
    concat_in = "".join(f"[v{i}]" for i in range(n))
    filt = ";".join(parts) + f";{concat_in}concat=n={n}:v=1:a=0[v]"
    cmd += ["-i", str(audio_path)]
    cmd += [
        "-filter_complex", filt,
        "-map", "[v]", "-map", f"{n}:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "17",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{total_duration:.3f}",
        "-movflags", "+faststart",
        str(out_p),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg beat scene composition failed:\n{res.stderr[-800:]}")
    return out_p
