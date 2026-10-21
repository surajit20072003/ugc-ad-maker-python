"""
pipeline/prompt_enhancer.py
────────────────────────────
Dedicated B-Roll Visual Prompt Enhancer — Fix 3.

Two-pass system (inspired by ai-document-presentation-v3's visual_prompt_enhancer_prompt.txt):
  Pass 1 (script_gen.py): Director writes raw Kling prompt (rough idea)
  Pass 2 (this module):   Enhancer rewrites it into 3 structured production fields:
                            - start_frame_prompt  (120+ words, opening keyframe)
                            - end_frame_prompt    (120+ words, closing keyframe)
                            - motion_prompt       (80+ words, SUBJECT/MECHANISM/CAMERA structure)

Ensures:
  - Voiceover-visual sync (laggy → buffering spinner, not a generic laptop)
  - Banned words removed (cinematic, beautiful, dynamic...)
  - Lighting anchor consistency across all beats in the same job
  - Cross-beat continuity via previous_end_hint
  - Zero-text enforcement suffix on all prompts
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE    = "https://openrouter.ai/api/v1/chat/completions"
ENHANCER_MODEL     = "anthropic/claude-sonnet-5"

# Load the system prompt from the prompts directory alongside this package
_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "broll_enhancer_system_prompt.txt"
_SYSTEM_PROMPT: str = ""


def _get_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if not _SYSTEM_PROMPT:
        try:
            _SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            # Inline fallback if file missing
            _SYSTEM_PROMPT = (
                "You are an elite UGC B-Roll Visual Prompt Enhancer. "
                "Return JSON with start_frame_prompt, end_frame_prompt, motion_prompt. "
                "Each frame prompt must be 120+ words. Motion prompt 80+ words. "
                "No banned words (cinematic/beautiful/dynamic/abstract/stunning). "
                "Output ONLY valid JSON, no markdown."
            )
    return _SYSTEM_PROMPT


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8765",
        "X-Title": "UGC Ad Maker B-Roll Enhancer",
    }


# Job-level lighting anchor — consistent across all B-roll beats
DEFAULT_LIGHTING_ANCHOR = (
    "Softbox key light from upper-left at 45 degrees, warm white 5500K. "
    "Subtle diffused fill light from right, 3200K. "
    "Deep neutral dark background with a soft gradient from near-black charcoal to very dark slate. "
    "No lens flare. No bloom. No distracting patterns."
)


async def enhance_broll_prompt(
    voiceover_text: str,
    raw_prompt: str,
    product_name: str,
    analysis: dict,
    mode: str = "physical",
    target_duration_sec: float = 8.0,
    lighting_anchor: str = "",
    previous_end_hint: str = "",
) -> dict:
    """
    Enhance a raw B-roll director prompt into production-quality IPS/IPE/VP.

    Args:
        voiceover_text:     The spoken voiceover for this segment (for sync check)
        raw_prompt:         The rough Kling prompt from the script director
        product_name:       Product name for context
        analysis:           Full analysis dict from analyze step
        mode:               "physical" or "software"
        target_duration_sec: Target clip duration in seconds
        lighting_anchor:    Job-level lighting description (shared across all beats)
        previous_end_hint:  End frame description from previous beat (for continuity)

    Returns:
        dict with keys: start_frame_prompt, end_frame_prompt, motion_prompt, visual_reasoning
    """
    colors = ", ".join(
        f"{c.get('name', '')} ({c.get('hex', '')})".strip("() ")
        for c in analysis.get("color_scheme", [])
    ) or "premium neutral commercial colors"
    brand       = analysis.get("brand_name", product_name)
    product_type = analysis.get("product_type", "product")
    visual_desc = analysis.get("visual_description", "clean premium product")
    device      = analysis.get("device_type", "laptop")
    use_case    = analysis.get("use_case", "solving the customer problem")

    if mode == "software":
        product_context = (
            f"Software/service: {product_name} by {brand}. Use case: {use_case}. "
            f"Device: unbranded {device}. "
            "Show abstract modern UI: clean cards, gradients, charts, layout blocks only. "
            "ZERO readable text, ZERO real app logos, ZERO real domain names."
        )
    else:
        product_context = (
            f"Physical product: {product_name} by {brand}. Type: {product_type}. "
            f"Visual details: {visual_desc}. Brand colors: {colors}. "
            "Show premium macro textures, clean packaging silhouette, tactile usage detail. "
            "No readable label text. No logos."
        )

    user_msg = f"""Enhance this B-roll beat into three production-quality prompt fields.

VOICEOVER TEXT (what creator says during this visual):
{voiceover_text}

RAW DIRECTOR PROMPT (rough idea to enhance):
{raw_prompt}

PRODUCT CONTEXT:
{product_context}

MODE: {mode}

LIGHTING ANCHOR (apply verbatim to all three prompts):
{lighting_anchor or DEFAULT_LIGHTING_ANCHOR}

TARGET CLIP DURATION: {target_duration_sec:.0f} seconds

{f"PREVIOUS BEAT END HINT (use for continuity if same scene/subject):{chr(10)}{previous_end_hint}" if previous_end_hint else ""}

Return ONLY valid JSON with exactly these keys: start_frame_prompt, end_frame_prompt, motion_prompt, visual_reasoning.
No markdown fences. No explanation."""

    payload = {
        "model": ENHANCER_MODEL,
        "messages": [
            {"role": "system", "content": _get_system_prompt()},
            {"role": "user",   "content": user_msg},
        ],
        "temperature": 0.45,
        "max_tokens": 2000,
    }

    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(OPENROUTER_BASE, headers=_headers(), json=payload)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()

    # Parse JSON — strip any accidental markdown fences
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        data = {}

    # Shared zero-text quality suffix appended to every frame prompt
    zero_text_suffix = (
        " No watermarks. No text overlays. No visible letters. No logos. No subtitles. "
        "No captions. Ultra-realistic 4K commercial photography quality. Vertical 9:16."
    )

    start = data.get("start_frame_prompt") or (
        f"Vertical 9:16 portrait orientation. 576x1024px. Photorealistic commercial photography. "
        f"{product_context} Opening static frame. {lighting_anchor or DEFAULT_LIGHTING_ANCHOR}"
    )
    end = data.get("end_frame_prompt") or (
        f"Vertical 9:16 portrait orientation. 576x1024px. Photorealistic commercial photography. "
        f"{product_context} Closing reveal frame. Same lighting. Same background. "
        f"{lighting_anchor or DEFAULT_LIGHTING_ANCHOR}"
    )
    motion = data.get("motion_prompt") or (
        f"SUBJECT: {product_name} in a premium commercial setting filling the center of frame. "
        "INITIAL STATE: Product positioned center-frame, fully in focus, lighting stable. "
        "MECHANISM: Camera performs a slow dolly push-in 3cm over full duration. Product remains static. "
        "RESULT: Product fills slightly more of frame, same lighting and background. "
        f"CAMERA: Slow dolly push-in. Fixed height. "
        f"DURATION: {target_duration_sec:.0f} seconds. 24fps. No text overlays. Vertical 9:16 format. No watermarks."
    )
    reasoning = data.get("visual_reasoning", "Enhanced B-roll prompt.")

    return {
        "start_frame_prompt": f"{start}{zero_text_suffix}",
        "end_frame_prompt":   f"{end}{zero_text_suffix}",
        "motion_prompt":      motion,
        "visual_reasoning":   reasoning,
    }
