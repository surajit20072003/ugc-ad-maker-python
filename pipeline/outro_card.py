"""
pipeline/outro_card.py
──────────────────────
Generate a clean brand outro card video appended to the final UGC ad.

The outro card is a 2.5-second full-screen card with:
  - Brand gradient background (derived from brand primary color)
  - Large brand/product name
  - Tagline from the analysis
  - Website/CTA in a colored pill badge
  - Subtle fade-in/out animation

All rendering is done via PIL/Pillow + FFmpeg — zero API cost.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

UPLOAD_DIR = Path(__file__).parent.parent / "uploads"

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
]


def _find_font(size: int = 48):
    try:
        from PIL import ImageFont
        for path in FONT_PATHS:
            if Path(path).exists():
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass
        return ImageFont.load_default()
    except Exception:
        return None


def _darken(rgb: Tuple[int, int, int], factor: float = 0.35) -> Tuple[int, int, int]:
    return tuple(max(0, int(c * factor)) for c in rgb)  # type: ignore


def _lighten(rgb: Tuple[int, int, int], factor: float = 1.55) -> Tuple[int, int, int]:
    return tuple(min(255, int(c * factor)) for c in rgb)  # type: ignore


def build_outro_card(
    brand_name: str,
    tagline: str = "",
    website: str = "",
    brand_color: Optional[Tuple[int, int, int]] = None,
    duration_sec: float = 2.5,
    output_path: Optional[Path] = None,
    width: int = 720,
    height: int = 1280,
) -> Path:
    """
    Generate a clean brand outro card video (PNG frame loop → MP4).

    Args:
        brand_name:   Main title shown large
        tagline:      Subtitle line below
        website:      CTA URL in a pill badge
        brand_color:  (R, G, B) primary brand color
        duration_sec: Duration of the outro card
        output_path:  Output MP4 path

    Returns:
        Path to the outro .mp4 file
    """
    if output_path is None:
        output_path = UPLOAD_DIR / f"outro_card_{abs(hash(brand_name))}.mp4"

    brand_rgb  = brand_color or (30, 80, 200)
    dark_rgb   = _darken(brand_rgb, 0.25)
    accent_rgb = _lighten(brand_rgb, 1.4)

    png_path = None
    try:
        from PIL import Image, ImageDraw

        img  = Image.new("RGB", (width, height), color=dark_rgb)
        draw = ImageDraw.Draw(img)

        # Vertical gradient background
        for y in range(height):
            t = y / height
            r = int(dark_rgb[0] + (brand_rgb[0] - dark_rgb[0]) * t)
            g = int(dark_rgb[1] + (brand_rgb[1] - dark_rgb[1]) * t)
            b = int(dark_rgb[2] + (brand_rgb[2] - dark_rgb[2]) * t)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        # Separator line
        sep_y = height // 2 - 70
        draw.rectangle([60, sep_y, width - 60, sep_y + 2], fill=accent_rgb)

        font_large = _find_font(72)
        font_med   = _find_font(40)
        font_small = _find_font(30)

        # Brand name
        bn = (brand_name or "Brand").upper()[:28]
        if font_large:
            try:
                bbox = draw.textbbox((0, 0), bn, font=font_large)
                tw = bbox[2] - bbox[0]
            except Exception:
                tw = len(bn) * 42
            tx = max(20, (width - tw) // 2)
            ty = height // 2 - 130
            draw.text((tx + 3, ty + 3), bn, font=font_large, fill=(0, 0, 0))
            draw.text((tx, ty), bn, font=font_large, fill=(255, 255, 255))

        # Tagline
        if tagline and font_med:
            tl = tagline[:60]
            try:
                bbox = draw.textbbox((0, 0), tl, font=font_med)
                tw = bbox[2] - bbox[0]
            except Exception:
                tw = len(tl) * 22
            tx = max(20, (width - tw) // 2)
            draw.text((tx, height // 2 - 20), tl, font=font_med, fill=(220, 220, 220))

        # Website CTA pill badge
        if website and font_small:
            ws = website[:50]
            pill_w, pill_h = 460, 56
            pill_x = (width - pill_w) // 2
            pill_y = height // 2 + 70
            try:
                draw.rounded_rectangle(
                    [pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
                    radius=28,
                    fill=accent_rgb,
                )
            except Exception:
                draw.rectangle([pill_x, pill_y, pill_x + pill_w, pill_y + pill_h], fill=accent_rgb)
            try:
                bbox = draw.textbbox((0, 0), ws, font=font_small)
                tw = bbox[2] - bbox[0]
            except Exception:
                tw = len(ws) * 16
            tx = pill_x + (pill_w - tw) // 2
            draw.text((tx, pill_y + 13), ws, font=font_small, fill=(255, 255, 255))

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            png_path = f.name
        img.save(png_path, "PNG")

    except Exception as pil_err:
        print(f"[OutroCard] PIL render failed ({pil_err}); falling back to FFmpeg drawtext.")
        png_path = None

    # Convert PNG → looping MP4 with fade-in/out
    fade_out_start = max(0.1, duration_sec - 0.4)
    if png_path and Path(png_path).exists():
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", png_path,
            "-vf", (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
                f"fade=t=in:st=0:d=0.4,"
                f"fade=t=out:st={fade_out_start:.2f}:d=0.4,"
                f"fps=30,format=yuv420p"
            ),
            "-t", f"{duration_sec:.2f}",
            "-c:v", "libx264", "-crf", "19", "-preset", "fast",
            "-an",
            "-movflags", "+faststart",
            str(output_path),
        ]
    else:
        r, g, b = brand_rgb
        hex_bg = f"0x{r:02X}{g:02X}{b:02X}"
        safe_name = (brand_name or "Brand")[:24].replace("'", "\\'").replace(":", "\\:")
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c={hex_bg}:size={width}x{height}:rate=30:duration={duration_sec:.2f}",
            "-vf", (
                f"drawtext=text='{safe_name}':fontsize=72:fontcolor=white:"
                f"x=(w-text_w)/2:y=(h-text_h)/2-60:shadowcolor=black:shadowx=2:shadowy=2,"
                f"fade=t=in:st=0:d=0.4,"
                f"fade=t=out:st={fade_out_start:.2f}:d=0.4,"
                f"fps=30,format=yuv420p"
            ),
            "-c:v", "libx264", "-crf", "19", "-preset", "fast",
            "-an",
            "-movflags", "+faststart",
            str(output_path),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if png_path:
        try:
            os.unlink(png_path)
        except Exception:
            pass

    if result.returncode != 0:
        raise RuntimeError(f"Outro card render failed:\n{result.stderr[-600:]}")

    return Path(output_path)
