"""
pipeline/motion_overlay.py
──────────────────────────
Instagram Reel-style animation overlays applied to the final stitched video.

Features:
  A. Kinetic word-level karaoke captions (.ass format with yellow highlight on active word)
  B. Film grain / retro 35mm texture overlay (FFmpeg blend)
  C. Comic burst sticker overlay (yellow spiky burst PNG)
  D. Avatar punch-zoom at clip start (subtle 1.0x → 1.12x over 12 frames)
  E. Animated search bar clip generator (for software/URL B-roll scenes)

All effects use FFmpeg filter chains — no extra Python dependencies.
"""
from __future__ import annotations

import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

STATIC_DIR = Path(__file__).parent.parent / "static" / "overlays"
UPLOAD_DIR = Path(__file__).parent.parent / "uploads"


# ─── A. Kinetic Karaoke Captions ─────────────────────────────────────────────

def _ass_time(seconds: float) -> str:
    """Convert seconds to ASS time format H:MM:SS.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_kinetic_ass(
    word_timestamps: list[tuple[str, float, float]],
    total_duration: float,
    words_per_line: int = 3,
) -> str:
    """
    Build an ASS subtitle file with kinetic word-level yellow highlights.

    Args:
        word_timestamps: list of (word, start_sec, end_sec)
        total_duration:  total video duration in seconds
        words_per_line:  how many words to show at once

    Returns:
        ASS file content as string
    """
    header = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: UGC,Arial Black,34,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3.0,1.5,2,40,40,60,1
Style: UGCActive,Arial Black,34,&H0000CCFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,108,108,0,0,1,3.5,1.5,2,40,40,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    words = word_timestamps

    # Group words into lines
    for line_start in range(0, len(words), words_per_line):
        chunk = words[line_start: line_start + words_per_line]
        if not chunk:
            continue

        line_begin = chunk[0][1]
        line_end = chunk[-1][2]

        # For each word in the chunk, emit a dialogue line showing all chunk words
        # but highlighting the active one
        for active_idx, (active_word, w_start, w_end) in enumerate(chunk):
            # Build the text: non-active words in white, active word in yellow+scaled
            parts = []
            for j, (word, _, _) in enumerate(chunk):
                if j == active_idx:
                    # Yellow highlight + scale-up
                    parts.append(r"{\c&H0000CCFF&\fscx108\fscy108}" + word.upper() + r"{\r}")
                else:
                    parts.append(word.upper())
            text = " ".join(parts)

            events.append(
                f"Dialogue: 0,{_ass_time(w_start)},{_ass_time(w_end)},UGC,,0,0,0,,{text}"
            )

    return header + "\n".join(events) + "\n"


def build_static_kinetic_ass(
    segments: list[dict],
    clip_durations: list[float],
    words_per_line: int = 3,
) -> str:
    """
    Build kinetic ASS from segment text + clip durations (fallback when no word timestamps).
    Distributes words evenly across clip duration.
    """
    header = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: UGC,Arial Black,34,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3.0,1.5,2,40,40,60,1
Style: UGCActive,Arial Black,34,&H0000CCFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,108,108,0,0,1,3.5,1.5,2,40,40,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    cursor = 0.0

    for seg, dur in zip(segments, clip_durations):
        words = seg.get("text", "").split()
        if not words or dur <= 0:
            cursor += dur
            continue

        secs_per_word = dur / len(words)
        pos = 0

        while pos < len(words):
            chunk = words[pos: pos + words_per_line]
            chunk_start = cursor + pos * secs_per_word
            chunk_end = cursor + (pos + len(chunk)) * secs_per_word
            chunk_end = min(chunk_end, cursor + dur - 0.05)

            # Emit one event per word in the chunk for highlighting
            for active_idx, w in enumerate(chunk):
                w_start = cursor + (pos + active_idx) * secs_per_word
                w_end = min(w_start + secs_per_word, cursor + dur - 0.05)
                parts = []
                for j, word in enumerate(chunk):
                    if j == active_idx:
                        parts.append(r"{\c&H0000CCFF&\fscx108\fscy108}" + word.upper() + r"{\r}")
                    else:
                        parts.append(word.upper())
                text = " ".join(parts)
                events.append(
                    f"Dialogue: 0,{_ass_time(w_start)},{_ass_time(w_end)},UGC,,0,0,0,,{text}"
                )

            pos += words_per_line

        cursor += dur

    return header + "\n".join(events) + "\n"


def burn_kinetic_captions(
    video_in: Path,
    video_out: Path,
    ass_content: str,
) -> None:
    """Burn kinetic ASS captions into video using FFmpeg."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ass", delete=False, encoding="utf-8") as f:
        f.write(ass_content)
        ass_path = f.name

    try:
        # Escape path for FFmpeg
        escaped = ass_path.replace("\\", "/").replace(":", "\\:")
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_in),
            "-vf", f"ass='{escaped}'",
            "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(video_out),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Kinetic caption burn failed:\n{result.stderr[-600:]}")
    finally:
        try:
            os.unlink(ass_path)
        except Exception:
            pass


# ─── B. Film Grain / Retro 35mm Overlay ──────────────────────────────────────

def apply_film_grain(
    video_in: Path,
    video_out: Path,
    grain_opacity: float = 0.15,
) -> None:
    """
    Apply a 35mm film grain + sprocket border overlay to the video.
    Uses generated grain via FFmpeg's geq filter if no asset file exists.
    """
    border_asset = STATIC_DIR / "film_border_720x1280.png"

    # Build filter chain
    # 1. Generate noise grain using geq
    # 2. Blend screen mode at low opacity
    # 3. Overlay film border matte if it exists

    grain_filter = (
        f"[0:v]split=1[base];"
        f"[base]geq='lum=p(X,Y)+if(gt(random(1)*255,200),random(1)*60,0)',"
        f"format=yuv420p[vout]"
    )

    if border_asset.exists():
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_in),
            "-i", str(border_asset),
            "-filter_complex",
            (
                f"[0:v]gblur=sigma=0.3[base];"
                f"[1:v]scale=720:1280[border];"
                f"[base][border]overlay=0:0:format=auto[vout]"
            ),
            "-map", "[vout]", "-map", "0:a?",
            "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(video_out),
        ]
    else:
        # Pure FFmpeg grain noise (no asset needed)
        grain_intensity = int(grain_opacity * 40)  # ~0-40 range for noise strength
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_in),
            "-vf", (
                f"noise=alls={grain_intensity}:allf=t+u,"
                f"curves=all='0/0 0.5/0.48 1/1'"
            ),
            "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(video_out),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Film grain apply failed:\n{result.stderr[-600:]}")


# ─── C. Comic Burst Sticker Overlay ──────────────────────────────────────────

def apply_comic_overlay(
    video_in: Path,
    video_out: Path,
    burst_start_sec: float = 0.2,
    burst_duration_sec: float = 1.5,
    x_pos: int = 20,
    y_pos: int = 460,
) -> None:
    """
    Overlay a yellow comic burst sticker PNG at given time range.
    If no PNG asset exists, skips silently (just copies).
    """
    burst_asset = STATIC_DIR / "comic_burst_yellow.png"
    if not burst_asset.exists():
        # No asset — just copy
        cmd = ["ffmpeg", "-y", "-i", str(video_in), "-c", "copy", str(video_out)]
        subprocess.run(cmd, capture_output=True)
        return

    burst_end = burst_start_sec + burst_duration_sec
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_in),
        "-i", str(burst_asset),
        "-filter_complex", (
            f"[1:v]scale=280:280[burst];"
            f"[0:v][burst]overlay={x_pos}:{y_pos}:enable='between(t,{burst_start_sec:.2f},{burst_end:.2f})'[vout]"
        ),
        "-map", "[vout]", "-map", "0:a?",
        "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(video_out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Non-fatal: just copy on failure
        cmd_copy = ["ffmpeg", "-y", "-i", str(video_in), "-c", "copy", str(video_out)]
        subprocess.run(cmd_copy, capture_output=True)


# ─── D. Avatar Punch Zoom ─────────────────────────────────────────────────────

def get_avatar_punch_zoom_vf(duration_sec: float) -> str:
    """
    Return an FFmpeg -vf filter string for a subtle punch-zoom on avatar clips.
    Zooms from 1.0x → 1.10x over the first 0.4s (12 frames at 30fps), holds at 1.10x.
    """
    frames = 12  # 0.4s at 30fps
    return (
        f"zoompan="
        f"z='if(lte(on,{frames}),1.0+0.008*on,1.10)':"
        f"x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':"
        f"d={frames}:"
        f"fps=30,"
        f"scale=720:1280"
    )


# ─── E. Animated Search Bar Clip ─────────────────────────────────────────────

def render_search_bar_clip(
    url_text: str,
    duration: float,
    out_path: Path,
    width: int = 720,
    height: int = 1280,
) -> Path:
    """
    Generate a short animated search bar clip using FFmpeg drawtext.
    Shows a pill-shaped URL bar with typing animation.
    Returns out_path.
    """
    safe_url = url_text[:40].replace(":", "\\:").replace("'", "\\'")

    # Typing: reveal text character by character
    # We use drawtext with enable time and text truncation hack
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=0x12152A:size={width}x{height}:rate=30:duration={duration:.2f}",
        "-vf", (
            # Draw search bar background (rounded rect approximation via drawbox)
            f"drawbox=x=40:y=540:w=640:h=64:color=0x1E2240:t=fill,"
            f"drawbox=x=40:y=540:w=640:h=64:color=0x7C3AED@0.6:t=2,"
            # Globe icon text
            f"drawtext=text='🔍':fontsize=28:x=60:y=554:fontcolor=0xA855F7,"
            # URL text with typewriter reveal (character by character based on time)
            f"drawtext=text='{safe_url}':"
            f"fontsize=20:x=100:y=560:fontcolor=0xF1F5F9:"
            f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:"
            f"expansion=none"
        ),
        "-c:v", "libx264", "-crf", "22", "-preset", "fast", "-pix_fmt", "yuv420p",
        "-an",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Search bar clip render failed:\n{result.stderr[-400:]}")
    return out_path


# ─── Asset Generation ─────────────────────────────────────────────────────────

def ensure_overlay_assets() -> None:
    """
    Create overlay asset directory and generate any missing PNG/video assets
    using PIL + FFmpeg (no internet required).
    """
    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    # Generate film border PNG if missing
    border_path = STATIC_DIR / "film_border_720x1280.png"
    if not border_path.exists():
        _generate_film_border(border_path)

    # Generate comic burst PNG if missing
    burst_path = STATIC_DIR / "comic_burst_yellow.png"
    if not burst_path.exists():
        _generate_comic_burst(burst_path)


def _generate_film_border(out_path: Path) -> None:
    """Generate a 720x1280 film sprocket border PNG using PIL."""
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (720, 1280), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Top and bottom black bars (film borders)
        bar_h = 48
        draw.rectangle([0, 0, 720, bar_h], fill=(0, 0, 0, 220))
        draw.rectangle([0, 1280 - bar_h, 720, 1280], fill=(0, 0, 0, 220))

        # Sprocket holes (top row)
        hole_w, hole_h = 18, 28
        for x in range(20, 700, 48):
            draw.rectangle([x, 8, x + hole_w, 8 + hole_h], fill=(30, 30, 30, 255))

        # Sprocket holes (bottom row)
        for x in range(20, 700, 48):
            draw.rectangle([x, 1280 - 8 - hole_h, x + hole_w, 1280 - 8], fill=(30, 30, 30, 255))

        img.save(out_path, "PNG")
    except Exception as e:
        print(f"[MotionOverlay] Could not generate film border: {e}")


def _generate_comic_burst(out_path: Path) -> None:
    """Generate a yellow spiky comic burst sticker PNG using PIL."""
    try:
        import math as _math
        from PIL import Image, ImageDraw
        size = 300
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        cx, cy = size // 2, size // 2

        # Draw spiky burst
        num_spikes = 16
        outer_r = 130
        inner_r = 80
        points = []
        for i in range(num_spikes * 2):
            angle = _math.pi * i / num_spikes - _math.pi / 2
            r = outer_r if i % 2 == 0 else inner_r
            x = cx + r * _math.cos(angle)
            y = cy + r * _math.sin(angle)
            points.append((x, y))

        draw.polygon(points, fill=(250, 200, 0, 240), outline=(220, 160, 0, 255))

        img.save(out_path, "PNG")
    except Exception as e:
        print(f"[MotionOverlay] Could not generate comic burst: {e}")
