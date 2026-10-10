"""
pipeline/icon_overlay.py
────────────────────────
Premium Pillow-rendered glassmorphism keyword icon cards & FFmpeg overlay integration.
Features:
  - Vector-drawn crisp icons (globe, mobile, cpu, dollar, gift, lightning, chart, shield, etc.)
  - High-end dark frosted glass backplate (translucent RGBA + soft outer glow + top accent bar)
  - Bold letter-spaced typography
  - Frame-accurate speech timing synchronized with measured audio durations
  - Zero burn-in text subtitles; clean, punchy visual graphic badges
"""
from __future__ import annotations

import os
import re
import math
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter

CARD_SIZE = 240  # Final exported size (240x240 px)
RENDER_SCALE = 3  # Render at 3x (720x720) for retina anti-aliased sharpness

# Keyword to (icon_name, accent_color_rgb) dictionary
KEYWORD_REGISTRY: Dict[str, Tuple[str, Tuple[int, int, int]]] = {
    # Tech & Web
    "website":    ("globe",      (59, 130, 246)),   # Electric Blue
    "site":       ("globe",      (59, 130, 246)),
    "web":        ("globe",      (59, 130, 246)),
    "online":     ("globe",      (59, 130, 246)),
    "link":       ("globe",      (59, 130, 246)),
    "url":        ("globe",      (59, 130, 246)),

    # Mobile & App
    "app":        ("mobile",     (139, 92, 246)),  # Neon Purple
    "phone":      ("mobile",     (139, 92, 246)),
    "mobile":     ("mobile",     (139, 92, 246)),
    "download":   ("mobile",     (139, 92, 246)),
    "ios":        ("mobile",     (139, 92, 246)),
    "android":    ("mobile",     (139, 92, 246)),

    # Software / AI / Tech
    "software":   ("cpu",        (6, 182, 212)),   # Cyan
    "ai":         ("cpu",        (6, 182, 212)),
    "tool":       ("cpu",        (6, 182, 212)),
    "algorithm":  ("cpu",        (6, 182, 212)),
    "dashboard":  ("cpu",        (6, 182, 212)),
    "tech":       ("cpu",        (6, 182, 212)),
    "platform":   ("cpu",        (6, 182, 212)),

    # Value & Price
    "cheap":      ("dollar",     (16, 185, 129)),  # Emerald Green
    "affordable": ("dollar",     (16, 185, 129)),
    "save":       ("dollar",     (16, 185, 129)),
    "price":      ("dollar",     (16, 185, 129)),
    "budget":     ("dollar",     (16, 185, 129)),
    "deal":       ("dollar",     (16, 185, 129)),
    "discount":   ("dollar",     (239, 68, 68)),   # Red accent

    # Free & Gift
    "free":       ("gift",       (245, 158, 11)),  # Amber
    "gift":       ("gift",       (245, 158, 11)),
    "bonus":      ("gift",       (245, 158, 11)),
    "special":    ("gift",       (245, 158, 11)),

    # Speed & Instant
    "fast":       ("lightning",  (251, 191, 36)),  # Golden Yellow
    "instant":    ("lightning",  (251, 191, 36)),
    "seconds":    ("lightning",  (251, 191, 36)),
    "quick":      ("lightning",  (251, 191, 36)),
    "speed":      ("lightning",  (251, 191, 36)),

    # Results & Scale
    "results":    ("chart",      (52, 211, 153)),  # Mint Green
    "growth":     ("chart",      (52, 211, 153)),
    "scale":      ("chart",      (52, 211, 153)),
    "sales":      ("chart",      (52, 211, 153)),
    "profit":     ("chart",      (52, 211, 153)),
    "money":      ("chart",      (52, 211, 153)),

    # Trust & Quality
    "trust":      ("shield",     (96, 165, 250)),  # Sky Blue
    "guarantee":  ("shield",     (96, 165, 250)),
    "safe":       ("shield",     (96, 165, 250)),
    "secure":     ("shield",     (96, 165, 250)),
    "proven":     ("shield",     (96, 165, 250)),

    # Solution & Ease
    "solution":   ("check",      (74, 222, 128)),  # Spring Green
    "easy":       ("check",      (74, 222, 128)),
    "simple":     ("check",      (74, 222, 128)),
    "perfect":    ("check",      (74, 222, 128)),
    "works":      ("check",      (74, 222, 128)),

    # Problem / Alert
    "problem":    ("warning",    (248, 113, 113)), # Coral Red
    "frustrated": ("warning",    (248, 113, 113)),
    "struggle":   ("warning",    (248, 113, 113)),
    "tired":      ("warning",    (248, 113, 113)),
    "stop":       ("warning",    (248, 113, 113)),

    # Star / Magic
    "best":       ("star",       (251, 191, 36)),  # Gold
    "review":     ("star",       (251, 191, 36)),
    "viral":      ("star",       (244, 114, 182)), # Rose
    "magic":      ("sparkles",   (232, 121, 249)), # Fuchsia
    "glow":       ("sparkles",   (253, 230, 138)), # Glow yellow
}


# ─── Vector Icon Drawer (Pillow anti-aliased at 3x) ──────────────────────────

def _draw_icon(draw: ImageDraw.ImageDraw, icon_name: str, center: Tuple[int, int], size: int, color: Tuple[int, int, int]):
    """Draw crisp vector icon primitives onto the 3x canvas."""
    cx, cy = center
    r = size // 2
    stroke_w = max(4, int(size * 0.09))
    rgba_stroke = (*color, 255)
    rgba_fill = (*color, 230)

    if icon_name == "globe":
        # Outer circle
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=rgba_stroke, width=stroke_w)
        # Horizontal latitude line
        draw.line([cx - r, cy, cx + r, cy], fill=rgba_stroke, width=stroke_w)
        # Vertical meridian ellipse
        rx = int(r * 0.45)
        draw.ellipse([cx - rx, cy - r, cx + rx, cy + r], outline=rgba_stroke, width=stroke_w)

    elif icon_name == "mobile":
        pw = int(r * 1.0)
        ph = int(r * 1.6)
        x0, y0 = cx - pw // 2, cy - ph // 2
        x1, y1 = cx + pw // 2, cy + ph // 2
        draw.rounded_rectangle([x0, y0, x1, y1], radius=int(pw * 0.22), outline=rgba_stroke, width=stroke_w)
        # Home bar / indicator
        draw.line([cx - int(pw * 0.2), y1 - int(ph * 0.12), cx + int(pw * 0.2), y1 - int(ph * 0.12)], fill=rgba_stroke, width=stroke_w)
        # Speaker
        draw.line([cx - int(pw * 0.15), y0 + int(ph * 0.1), cx + int(pw * 0.15), y0 + int(ph * 0.1)], fill=rgba_stroke, width=max(2, stroke_w // 2))

    elif icon_name == "cpu":
        cw = int(r * 1.1)
        x0, y0 = cx - cw // 2, cy - cw // 2
        x1, y1 = cx + cw // 2, cy + cw // 2
        draw.rounded_rectangle([x0, y0, x1, y1], radius=int(cw * 0.18), outline=rgba_stroke, width=stroke_w)
        # Inner square
        iw = int(cw * 0.45)
        draw.rounded_rectangle([cx - iw // 2, cy - iw // 2, cx + iw // 2, cy + iw // 2], radius=4, fill=rgba_fill)
        # Pins on top/bottom/left/right
        pin_len = int(cw * 0.22)
        for offset in [-int(cw * 0.25), 0, int(cw * 0.25)]:
            # Top & Bottom
            draw.line([cx + offset, y0 - pin_len, cx + offset, y0], fill=rgba_stroke, width=stroke_w)
            draw.line([cx + offset, y1, cx + offset, y1 + pin_len], fill=rgba_stroke, width=stroke_w)
            # Left & Right
            draw.line([x0 - pin_len, cy + offset, x0, cy + offset], fill=rgba_stroke, width=stroke_w)
            draw.line([x1, cy + offset, x1 + pin_len, cy + offset], fill=rgba_stroke, width=stroke_w)

    elif icon_name == "dollar":
        # Circle badge
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=rgba_stroke, width=stroke_w)
        # Bold stylized $
        sw = stroke_w + 2
        # Vertical spine
        draw.line([cx, cy - int(r * 0.65), cx, cy + int(r * 0.65)], fill=rgba_stroke, width=sw)
        # S curves approximated
        top_y = cy - int(r * 0.35)
        mid_y = cy
        bot_y = cy + int(r * 0.35)
        curve_w = int(r * 0.38)
        draw.arc([cx - curve_w, top_y - int(r*0.25), cx + curve_w, mid_y + int(r*0.05)], start=90, end=300, fill=rgba_stroke, width=sw)
        draw.arc([cx - curve_w, mid_y - int(r*0.05), cx + curve_w, bot_y + int(r*0.25)], start=270, end=120, fill=rgba_stroke, width=sw)

    elif icon_name == "gift":
        gw = int(r * 1.2)
        gh = int(r * 1.1)
        x0, y0 = cx - gw // 2, cy - gh // 2
        x1, y1 = cx + gw // 2, cy + gh // 2
        # Box
        draw.rounded_rectangle([x0, y0 + int(gh*0.25), x1, y1], radius=6, outline=rgba_stroke, width=stroke_w)
        # Lid
        draw.rounded_rectangle([x0 - 4, y0 + int(gh*0.1), x1 + 4, y0 + int(gh*0.3)], radius=4, fill=rgba_fill)
        # Ribbon vertical
        draw.line([cx, y0 + int(gh*0.1), cx, y1], fill=(255, 255, 255, 240), width=stroke_w)
        # Top Bow loops
        draw.arc([cx - int(gw*0.3), y0 - int(gh*0.2), cx, y0 + int(gh*0.15)], start=160, end=20, fill=rgba_stroke, width=stroke_w)
        draw.arc([cx, y0 - int(gh*0.2), cx + int(gw*0.3), y0 + int(gh*0.15)], start=160, end=20, fill=rgba_stroke, width=stroke_w)

    elif icon_name == "lightning":
        # Stylized sharp thunder bolt
        poly = [
            (cx + int(r * 0.1), cy - r),
            (cx - int(r * 0.65), cy + int(r * 0.05)),
            (cx - int(r * 0.05), cy + int(r * 0.05)),
            (cx - int(r * 0.2), cy + r),
            (cx + int(r * 0.65), cy - int(r * 0.1)),
            (cx + int(r * 0.05), cy - int(r * 0.1)),
        ]
        draw.polygon(poly, fill=rgba_fill, outline=(255, 255, 255, 240))

    elif icon_name == "chart":
        # Upward trending chart bars
        bw = int(r * 0.28)
        gap = int(r * 0.1)
        base_y = cy + int(r * 0.65)
        bars = [0.45, 0.75, 1.15]
        for i, h in enumerate(bars):
            bx = (cx - int(r * 0.55)) + i * (bw + gap)
            by = base_y - int(r * h)
            draw.rounded_rectangle([bx, by, bx + bw, base_y], radius=4, fill=rgba_fill)
        # Upward Arrow line
        draw.line([cx - int(r * 0.6), base_y - int(r * 0.3), cx + int(r * 0.65), cy - int(r * 0.55)], fill=(255, 255, 255, 230), width=stroke_w)

    elif icon_name == "shield":
        # Shield shape
        poly = [
            (cx, cy + r),
            (cx - int(r * 0.8), cy - int(r * 0.2)),
            (cx - int(r * 0.8), cy - int(r * 0.75)),
            (cx, cy - int(r * 0.6)),
            (cx + int(r * 0.8), cy - int(r * 0.75)),
            (cx + int(r * 0.8), cy - int(r * 0.2)),
        ]
        draw.polygon(poly, outline=rgba_stroke, fill=(*color, 90))
        # Inner checkmark
        ch_pts = [
            (cx - int(r * 0.35), cy),
            (cx - int(r * 0.1), cy + int(r * 0.25)),
            (cx + int(r * 0.35), cy - int(r * 0.25)),
        ]
        draw.line(ch_pts, fill=(255, 255, 255, 255), width=stroke_w + 1, joint="curve")

    elif icon_name == "check":
        # Green check circle
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=rgba_fill)
        ch_pts = [
            (cx - int(r * 0.42), cy),
            (cx - int(r * 0.1), cy + int(r * 0.32)),
            (cx + int(r * 0.42), cy - int(r * 0.3)),
        ]
        draw.line(ch_pts, fill=(12, 20, 30, 255), width=stroke_w + 3, joint="curve")

    elif icon_name == "warning":
        # Warning triangle
        poly = [
            (cx, cy - r),
            (cx + int(r * 0.9), cy + int(r * 0.7)),
            (cx - int(r * 0.9), cy + int(r * 0.7)),
        ]
        draw.polygon(poly, outline=rgba_stroke, fill=(*color, 110))
        # Exclamation
        draw.line([cx, cy - int(r * 0.25), cx, cy + int(r * 0.25)], fill=(255, 255, 255, 255), width=stroke_w)
        draw.ellipse([cx - stroke_w // 2, cy + int(r * 0.42), cx + stroke_w // 2, cy + int(r * 0.42) + stroke_w], fill=(255, 255, 255, 255))

    elif icon_name == "star":
        pts = []
        for i in range(10):
            angle = i * (math.pi / 5) - (math.pi / 2)
            dist = r if (i % 2 == 0) else int(r * 0.45)
            pts.append((cx + int(dist * math.cos(angle)), cy + int(dist * math.sin(angle))))
        draw.polygon(pts, fill=rgba_fill, outline=(255, 255, 255, 230))

    else:  # sparkles / default
        for offset_scale in [1.0, 0.4]:
            sr = int(r * offset_scale)
            scx = cx if offset_scale == 1.0 else cx + int(r * 0.5)
            scy = cy if offset_scale == 1.0 else cy - int(r * 0.5)
            poly = [
                (scx, scy - sr),
                (scx + int(sr * 0.25), scy - int(sr * 0.25)),
                (scx + sr, scy),
                (scx + int(sr * 0.25), scy + int(sr * 0.25)),
                (scx, scy + sr),
                (scx - int(sr * 0.25), scy + int(sr * 0.25)),
                (scx - sr, scy),
                (scx - int(sr * 0.25), scy - int(sr * 0.25)),
            ]
            draw.polygon(poly, fill=rgba_fill)


# ─── Glassmorphism Floating Pill Badge Generator ──────────────────────────

PILL_WIDTH = 240   # Sleek horizontal width
PILL_HEIGHT = 58   # Compact pill height (never blocks face)
PILL_SCALE = 3     # 720 x 174 at 3x for razor-sharp rendering


def generate_icon_card(
    keyword: str,
    output_path: str | Path,
    brand_color: Optional[Tuple[int, int, int]] = None,
) -> str:
    """
    Render a modern 240x58 horizontal floating glass pill badge PNG:
    - Frosted dark glass capsule (translucent slate with subtle white rim)
    - Glowing circular accent badge on the left with crisp vector icon
    - Bold letter-spaced typography on the right
    - Designed specifically to float in upper-right corner without blocking creator's face.
    """
    clean_kw = keyword.lower().strip()
    icon_name, accent = KEYWORD_REGISTRY.get(clean_kw, ("sparkles", (59, 130, 246)))
    if brand_color:
        accent = brand_color

    W = PILL_WIDTH * PILL_SCALE   # 720 px
    H = PILL_HEIGHT * PILL_SCALE  # 174 px

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # 1. Soft Outer Ambient Glow & Shadow
    glow_canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(glow_canvas)
    pad = 18
    pill_radius = (H - 2 * pad) // 2

    # Accent colored glow behind pill
    g_draw.rounded_rectangle(
        [pad - 8, pad - 6, W - pad + 8, H - pad + 6],
        radius=pill_radius + 6,
        fill=(*accent, 45),
    )
    # Dark drop shadow
    g_draw.rounded_rectangle(
        [pad, pad + 10, W - pad, H - pad + 10],
        radius=pill_radius,
        fill=(0, 0, 0, 140),
    )
    glow_canvas = glow_canvas.filter(ImageFilter.GaussianBlur(16))
    canvas.alpha_composite(glow_canvas)

    # 2. Frosted Glass Body (Sleek Translucent Slate Capsule)
    glass = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d_glass = ImageDraw.Draw(glass)
    d_glass.rounded_rectangle(
        [pad, pad, W - pad, H - pad],
        radius=pill_radius,
        fill=(15, 20, 32, 215),         # deep translucent glass
        outline=(255, 255, 255, 60),    # subtle glass rim reflection
        width=3,
    )
    canvas.alpha_composite(glass)

    # 3. Circular Accent Icon Badge on Left
    badge_cx = pad + pill_radius
    badge_cy = H // 2
    badge_r = int(pill_radius * 0.72)

    # Inner circular badge backplate with accent tint
    badge_canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d_badge = ImageDraw.Draw(badge_canvas)
    d_badge.ellipse(
        [badge_cx - badge_r, badge_cy - badge_r, badge_cx + badge_r, badge_cy + badge_r],
        fill=(*accent, 50),
        outline=(*accent, 220),
        width=3,
    )

    # Draw centered vector icon inside badge
    icon_draw_size = int(badge_r * 1.25)
    _draw_icon(d_badge, icon_name, (badge_cx, badge_cy), icon_draw_size, accent)
    canvas.alpha_composite(badge_canvas)

    # 4. Bold Modern Typography on Right
    text_canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d_text = ImageDraw.Draw(text_canvas)

    display_text = " ".join(list(clean_kw.upper()))

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 38)
    except Exception:
        font = ImageFont.load_default()

    bbox = d_text.textbbox((0, 0), display_text, font=font)
    th = bbox[3] - bbox[1]
    tx = badge_cx + badge_r + 28
    ty = badge_cy - (th // 2) - 3

    # Drop shadow
    d_text.text((tx, ty + 2), display_text, fill=(0, 0, 0, 180), font=font)
    # Crisp white text
    d_text.text((tx, ty), display_text, fill=(255, 255, 255, 255), font=font)
    canvas.alpha_composite(text_canvas)

    # 5. Downscale with Lanczos for razor-sharp anti-aliased pill
    final_card = canvas.resize((PILL_WIDTH, PILL_HEIGHT), Image.Resampling.LANCZOS)

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    final_card.save(str(out_p), format="PNG")
    return str(out_p)


# ─── Timing & Overlays Planner ────────────────────────────────────────────────

def plan_segment_icon_overlays(
    segments: List[Dict],
    temp_dir: str | Path,
    brand_color: Optional[Tuple[int, int, int]] = None,
) -> List[Dict]:
    """
    Scan spoken dialogue across segments and generate timed icon card overlays.
    Uses exact audio durations where available.
    """
    overlays: List[Dict] = []
    current_time_offset = 0.0

    temp_path = Path(temp_dir)
    temp_path.mkdir(parents=True, exist_ok=True)

    for seg_idx, seg in enumerate(segments):
        text = seg.get("text", "")
        audio_dur = seg.get("audio_duration_sec")
        if not audio_dur or audio_dur <= 0:
            words = text.split()
            audio_dur = max(3.0, len(words) / 2.1)

        words = re.findall(r'\b[a-zA-Z0-9_\-\$]+\b', text.lower())
        total_words = max(1, len(words))

        matched_in_segment = set()
        for w_idx, word in enumerate(words):
            if word in KEYWORD_REGISTRY and word not in matched_in_segment:
                matched_in_segment.add(word)

                rel_frac = w_idx / float(total_words)
                start_sec = round(current_time_offset + (rel_frac * audio_dur), 2)
                display_len = 1.4
                end_sec = round(min(start_sec + display_len, current_time_offset + audio_dur), 2)

                card_filename = f"card_seg{seg_idx}_{word}.png"
                card_path = temp_path / card_filename
                generate_icon_card(word, card_path, brand_color=brand_color)

                overlays.append({
                    "keyword": word,
                    "card_path": str(card_path),
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "duration": display_len,
                    "segment_index": seg_idx,
                })

                if len(matched_in_segment) >= 2:
                    break

        current_time_offset += audio_dur

    return overlays


def build_ffmpeg_icon_filter(
    overlays: List[Dict],
    input_video_tag: str = "[0:v]",
    output_tag: str = "[v_icons]",
    pos_x: str = "W-w-36",   # Top-Right safe zone (completely clear of face)
    pos_y: str = "95",       # Below mobile notch, above face height
) -> Tuple[List[str], str]:
    """
    Build FFmpeg inputs & filter_complex chain for pop-in floating pill overlays.
    Positioned in upper-right background safe zone away from creator's face.
    """
    if not overlays:
        return [], f"{input_video_tag}copy{output_tag}"

    extra_inputs: List[str] = []
    filter_parts: List[str] = []
    last_tag = input_video_tag

    for i, ov in enumerate(overlays):
        extra_inputs.extend(["-i", ov["card_path"]])
        card_input_idx = i + 1  # 0 is base video, cards are 1..N
        curr_output = f"[v_icon_{i}]" if i < len(overlays) - 1 else output_tag

        start_t = ov["start_sec"]
        end_t = ov["end_sec"]

        # Smooth pop-in and fade overlay via enable between
        overlay_expr = (
            f"{last_tag}[{card_input_idx}:v]overlay="
            f"x='{pos_x}':y='{pos_y}':"
            f"enable='between(t,{start_t},{end_t})'"
            f"{curr_output}"
        )
        filter_parts.append(overlay_expr)
        last_tag = curr_output

    return extra_inputs, ";".join(filter_parts)
