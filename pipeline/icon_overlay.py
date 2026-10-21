"""
pipeline/icon_overlay.py
────────────────────────
Elite Glassmorphism Keyword Icon Badges & FFmpeg Overlay Integration:
Features:
  - Vector SVG Lucide icon primitives (globe, mobile, cpu, dollar, gift, lightning, chart, shield, etc.)
  - Dual-tone frosted glass capsule backplate with specular edge reflections and ambient glow
  - High-impact modern typography (bold uppercase with subtle shadow)
  - Frame-accurate speech timing synchronized with measured audio durations
  - Smooth 250ms alpha fade-in and fade-out animations via FFmpeg filtergraph
  - Safe upper-right screen positioning clear of facial and product focal zones
"""
from __future__ import annotations

import os
import re
import html
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter

CARD_WIDTH = 260
CARD_HEIGHT = 60

# SVG Lucide Icon Library (ViewBox 0 0 24 24)
SVG_ICONS: Dict[str, str] = {
    "globe": '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
    "mobile": '<rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/>',
    "cpu": '<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>',
    "dollar": '<line x1="12" x2="12" y1="2" y2="22"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    "gift": '<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M12 8v13"/><path d="M19 12v7a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-7"/><path d="M7.5 8a2.5 2.5 0 0 1 0-5A4.8 4.8 0 0 1 12 8a4.8 4.8 0 0 1 4.5-5 2.5 2.5 0 0 1 0 5"/>',
    "lightning": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    "chart": '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/><path d="m9 12 2 2 4-4"/>',
    "check": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "warning": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    "star": '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    "sparkles": '<path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/><path d="M5 3v4"/><path d="M3 5h4"/><path d="M19 17v4"/><path d="M17 19h4"/>',
    "heart": '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/>',
    "cart": '<path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/>',
    "tag": '<path d="M12 2H2v10l9.29 9.29c.94.94 2.48.94 3.42 0l6.58-6.58c.94-.94.94-2.48 0-3.42L12 2Z"/><circle cx="7" cy="7" r=".5" fill="currentColor"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "fire": '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>'
}

# Keyword Registry: keyword -> (icon_name, accent_hex_str, badge_title)
KEYWORD_CONFIG: Dict[str, Tuple[str, str, str]] = {
    # Tech & Web
    "website":    ("globe",     "#3b82f6", "OFFICIAL SITE"),
    "site":       ("globe",     "#3b82f6", "VISIT WEBSITE"),
    "web":        ("globe",     "#3b82f6", "ONLINE NOW"),
    "online":     ("globe",     "#3b82f6", "ONLINE ACCESS"),
    "link":       ("globe",     "#3b82f6", "LINK IN BIO"),
    "url":        ("globe",     "#3b82f6", "VISIT LINK"),

    # Mobile & App
    "app":        ("mobile",    "#8b5cf6", "MOBILE APP"),
    "phone":      ("mobile",    "#8b5cf6", "MOBILE FRIENDLY"),
    "mobile":     ("mobile",    "#8b5cf6", "MOBILE APP"),
    "download":   ("mobile",    "#8b5cf6", "GET APP"),
    "ios":        ("mobile",    "#8b5cf6", "IOS & ANDROID"),
    "android":    ("mobile",    "#8b5cf6", "ANDROID APP"),

    # AI & Software
    "software":   ("cpu",       "#06b6d4", "SMART SOFTWARE"),
    "ai":         ("cpu",       "#06b6d4", "AI POWERED"),
    "tool":       ("cpu",       "#06b6d4", "SMART TOOL"),
    "algorithm":  ("cpu",       "#06b6d4", "ADVANCED TECH"),
    "dashboard":  ("cpu",       "#06b6d4", "DASHBOARD"),
    "tech":       ("cpu",       "#06b6d4", "NEXT-GEN TECH"),
    "platform":   ("cpu",       "#06b6d4", "CLOUD PLATFORM"),

    # Price & Value
    "cheap":      ("dollar",    "#10b981", "AFFORDABLE"),
    "affordable": ("dollar",    "#10b981", "BUDGET FRIENDLY"),
    "save":       ("dollar",    "#10b981", "SAVE BIG"),
    "price":      ("dollar",    "#10b981", "BEST PRICE"),
    "budget":     ("dollar",    "#10b981", "LOW COST"),
    "deal":       ("tag",       "#ef4444", "SPECIAL DEAL"),
    "discount":   ("tag",       "#ef4444", "LIMITED DISCOUNT"),
    "sale":       ("tag",       "#ef4444", "FLASH SALE"),
    "off":        ("tag",       "#ef4444", "SAVE 50%"),

    # Free & Gifts
    "free":       ("gift",      "#f59e0b", "100% FREE"),
    "gift":       ("gift",      "#f59e0b", "FREE GIFT"),
    "bonus":      ("gift",      "#f59e0b", "EXCLUSIVE BONUS"),
    "special":    ("gift",      "#f59e0b", "SPECIAL OFFER"),

    # Speed
    "fast":       ("lightning", "#fbbf24", "SUPER FAST"),
    "instant":    ("lightning", "#fbbf24", "INSTANT RESULTS"),
    "seconds":    ("lightning", "#fbbf24", "UNDER 60 SECS"),
    "quick":      ("lightning", "#fbbf24", "QUICK SETUP"),
    "speed":      ("lightning", "#fbbf24", "LIGHTNING FAST"),

    # Results & Trust
    "results":    ("chart",     "#34d399", "PROVEN RESULTS"),
    "growth":     ("chart",     "#34d399", "FAST GROWTH"),
    "scale":      ("chart",     "#34d399", "SCALE EFFORTLESSLY"),
    "sales":      ("chart",     "#34d399", "BOOST SALES"),
    "profit":     ("chart",     "#34d399", "HIGH ROI"),
    "trust":      ("shield",    "#60a5fa", "VERIFIED TRUSTED"),
    "guarantee":  ("shield",    "#60a5fa", "100% GUARANTEED"),
    "safe":       ("shield",    "#60a5fa", "SAFE & SECURE"),
    "secure":     ("shield",    "#60a5fa", "ENCRYPTED & SAFE"),
    "proven":     ("shield",    "#60a5fa", "PROVEN RESULTS"),

    # Solution & Simplicity
    "solution":   ("check",     "#4ade80", "PERFECT SOLUTION"),
    "easy":       ("check",     "#4ade80", "SUPER EASY"),
    "simple":     ("check",     "#4ade80", "1-CLICK EASY"),
    "perfect":    ("check",     "#4ade80", "PERFECT FIT"),
    "works":      ("check",     "#4ade80", "IT REALLY WORKS"),

    # Problem / Alert
    "problem":    ("warning",   "#f87171", "STOP STRUGGLING"),
    "frustrated": ("warning",   "#f87171", "TIRED OF THIS?"),
    "struggle":   ("warning",   "#f87171", "NO MORE HASSLE"),
    "tired":      ("warning",   "#f87171", "TIRED OF WAITING?"),
    "stop":       ("warning",   "#f87171", "STOP WASTING TIME"),

    # High Rating / Trend
    "best":       ("star",      "#fbbf24", "RATED #1"),
    "review":     ("star",      "#fbbf24", "5-STAR RATED"),
    "viral":      ("fire",      "#f97316", "VIRAL TREND"),
    "trending":   ("fire",      "#f97316", "TRENDING NOW"),
    "magic":      ("sparkles",  "#e879f9", "MAGICAL EFFECT"),
    "glow":       ("sparkles",  "#fde047", "NATURAL GLOW"),
    "love":       ("heart",     "#f43f5e", "FAN FAVORITE"),
    "obsessed":   ("heart",     "#f43f5e", "TOTALLY OBSESSED"),
    "order":      ("cart",      "#10b981", "ORDER TODAY"),
    "buy":        ("cart",      "#10b981", "LIMITED STOCK"),
    "time":       ("clock",     "#0ea5e9", "SAVE YOUR TIME"),
}

# Compatibility mapping
KEYWORD_REGISTRY: Dict[str, Tuple[str, Tuple[int, int, int]]] = {
    kw: (
        cfg[0],
        (
            int(cfg[1][1:3], 16),
            int(cfg[1][3:5], 16),
            int(cfg[1][5:7], 16)
        )
    )
    for kw, cfg in KEYWORD_CONFIG.items()
}


def _rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def generate_icon_card(
    keyword: str,
    output_path: str | Path,
    brand_color: Optional[Tuple[int, int, int]] = None,
) -> str:
    """
    Render an ultra-premium 260x60 glassmorphism pill badge PNG:
    - Frosted dark glass backplate with specular edge reflections and soft ambient shadow
    - Glowing circular accent badge with crisp vector SVG Lucide icon
    - Modern bold typography with drop shadow
    - Razor-sharp vector rendering via librsvg / ffmpeg
    """
    clean_kw = keyword.lower().strip()
    cfg = KEYWORD_CONFIG.get(clean_kw)

    if cfg:
        icon_name, accent_hex, label_text = cfg
    else:
        icon_name = "sparkles"
        accent_hex = "#3b82f6"
        label_text = clean_kw.upper()

    if brand_color:
        accent_hex = _rgb_to_hex(brand_color)

    icon_svg_content = SVG_ICONS.get(icon_name, SVG_ICONS["sparkles"])
    escaped_label = html.escape(label_text)

    # 3x vector dimensions for retina clarity (780 x 180)
    svg_markup = f"""<svg xmlns="http://www.w3.org/2000/svg" width="780" height="180" viewBox="0 0 780 180">
  <defs>
    <!-- Drop Shadow & Soft Ambient Glow -->
    <filter id="badgeShadow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="12" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
    <!-- Dark Frosted Glass Backplate -->
    <linearGradient id="glassBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0b1120" stop-opacity="0.90" />
      <stop offset="100%" stop-color="#0f172a" stop-opacity="0.96" />
    </linearGradient>
    <!-- Dual-Tone Specular Rim Border -->
    <linearGradient id="rimBorder" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="rgba(255,255,255,0.48)" />
      <stop offset="45%" stop-color="{accent_hex}" stop-opacity="0.85" />
      <stop offset="100%" stop-color="rgba(255,255,255,0.15)" />
    </linearGradient>
    <!-- Accent Badge Glow -->
    <linearGradient id="iconBadgeBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{accent_hex}" stop-opacity="0.38" />
      <stop offset="100%" stop-color="{accent_hex}" stop-opacity="0.14" />
    </linearGradient>
  </defs>

  <!-- Ambient Dark Shadow -->
  <rect x="25" y="20" width="730" height="140" rx="70" fill="rgba(0,0,0,0.6)" filter="url(#badgeShadow)" />

  <!-- Frosted Glass Capsule -->
  <rect x="25" y="15" width="730" height="150" rx="75" fill="url(#glassBg)" stroke="url(#rimBorder)" stroke-width="3.5" />

  <!-- Circular Icon Accent Container -->
  <circle cx="102" cy="90" r="54" fill="url(#iconBadgeBg)" stroke="{accent_hex}" stroke-width="3" />

  <!-- Crisp Vector Icon -->
  <g transform="translate(77, 65) scale(2.25)" stroke="{accent_hex}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" fill="none">
    {icon_svg_content}
  </g>

  <!-- High-Contrast Bold Typography -->
  <!-- Shadow offset -->
  <text x="182" y="104" font-family="DejaVu Sans, Arial, sans-serif" font-weight="bold" font-size="38" fill="rgba(0,0,0,0.7)" letter-spacing="1.2">{escaped_label}</text>
  <!-- Foreground text -->
  <text x="180" y="102" font-family="DejaVu Sans, Arial, sans-serif" font-weight="bold" font-size="38" fill="#ffffff" letter-spacing="1.2">{escaped_label}</text>
</svg>"""

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    # Convert SVG to PNG using ffmpeg's librsvg engine
    temp_svg = out_p.with_suffix(".svg")
    try:
        temp_svg.write_text(svg_markup, encoding="utf-8")
        cmd = [
            "ffmpeg", "-y",
            "-i", str(temp_svg),
            "-vf", f"scale={CARD_WIDTH}:{CARD_HEIGHT}:flags=lanczos",
            str(out_p)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg SVG rasterization failed: {res.stderr}")
    finally:
        if temp_svg.exists():
            temp_svg.unlink()

    return str(out_p)


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
            if word in KEYWORD_CONFIG and word not in matched_in_segment:
                matched_in_segment.add(word)

                rel_frac = w_idx / float(total_words)
                start_sec = round(current_time_offset + (rel_frac * audio_dur), 2)
                display_len = 1.6
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
    pos_x: str = "W-w-36",   # Top-Right safe zone clear of face and product center
    base_y: int = 95,        # Below mobile status bar / safe margin
) -> Tuple[List[str], str]:
    """
    Build FFmpeg inputs & filter_complex chain for smooth pop-in floating pill overlays.
    Incorporates smooth slide-down entrance and exit motions.
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

        # Dynamic smooth slide-down entrance and slide-up exit
        slide_expr_y = (
            f"if(lt(t,{start_t}+0.25), {base_y}-25*(1-(t-{start_t})/0.25), "
            f"if(gt(t,{end_t}-0.25), {base_y}-25*((t-({end_t}-0.25))/0.25), {base_y}))"
        )

        overlay_expr = (
            f"{last_tag}[{card_input_idx}:v]overlay="
            f"x='{pos_x}':y='{slide_expr_y}':"
            f"enable='between(t,{start_t},{end_t})'"
            f"{curr_output}"
        )
        filter_parts.append(overlay_expr)
        last_tag = curr_output

    return extra_inputs, ";".join(filter_parts)
