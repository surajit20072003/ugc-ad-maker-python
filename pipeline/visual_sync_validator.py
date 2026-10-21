"""
pipeline/visual_sync_validator.py
──────────────────────────────────
Fix 5: B-Roll Voiceover-Visual Sync Validator & Prompt Sanitizer.

Guarantees that:
1. When voiceover mentions specific concepts (laggy, fast, secure, results, etc.),
   the visual prompts contain literal, physical evidence of that concept rather than
   a generic object shot (e.g. laptop alone).
2. Any banned words (cinematic, beautiful, dynamic, etc.) are stripped or replaced with
   concrete physical descriptors.
3. Quality suffixes and 9:16 vertical formatting rules remain intact.
"""
from __future__ import annotations

import re
from typing import Dict

# Rule-based voiceover concept -> concrete physical visual requirements
VOICEOVER_TO_VISUAL_MAP = {
    ("laggy", "slow", "sluggish", "buggy", "frozen", "loading forever", "stuck"): {
        "required_terms": ["frozen", "buffering", "spinner", "stuck", "loading bar", "hourglass", "lag"],
        "inject_desc": "Display screen visibly shows a frozen interface with a spinning circular buffering indicator and a stuck progress bar.",
    },
    ("fast", "instant", "quick", "lightning", "speed", "rapid"): {
        "required_terms": ["instantly", "fluid", "rapidly", "completing", "immediate", "speed", "swift"],
        "inject_desc": "Display screen visibly shows high-speed performance: a responsive progress bar completing to 100% instantly.",
    },
    ("secure", "safe", "privacy", "protect", "encrypted", "trust"): {
        "required_terms": ["padlock", "shield", "secure", "lock", "badge", "ssl", "protection"],
        "inject_desc": "Visual includes a glowing security padlock clicking shut and a verified shield badge indicator.",
    },
    ("save", "cheap", "cost", "price", "affordable", "expensive", "discount"): {
        "required_terms": ["price", "comparison", "cost", "dollar", "savings", "table", "graph"],
        "inject_desc": "Visual features a side-by-side comparison panel displaying price contrast and a green savings metric.",
    },
    ("easy", "simple", "effortless", "in seconds", "one click", "1-click"): {
        "required_terms": ["1-2-3", "step", "single tap", "tap gesture", "simple flow", "clean flow"],
        "inject_desc": "Visual features a clean 3-step visual sequence completing effortlessly with a single finger tap gesture.",
    },
    ("results", "growth", "revenue", "scale", "performance", "metrics"): {
        "required_terms": ["graph", "chart", "metric", "counter", "upward", "analytics"],
        "inject_desc": "Visual features a glowing upward-trending analytics line chart with an active metric counter.",
    },
}

BANNED_WORDS = [
    r"\bcinematic\b",
    r"\bbeautiful\b",
    r"\bdynamic\b",
    r"\babstract\b",
    r"\bsmooth_animation\b",
    r"\bflows_gracefully\b",
    r"\belegantly\b",
    r"\belegant\b",
    r"\bstunning\b",
    r"\bdramatic\b",
    r"\bseamlessly\b",
    r"\bbreathtaking\b",
    r"\bgorgeous\b",
    r"\bamazing\b",
    r"\bvisually_appealing\b",
]


def sanitize_banned_words(text: str) -> str:
    """Remove fluffy/generic buzzwords that degrade AI image and video quality."""
    if not text:
        return ""
    result = text
    for pattern in BANNED_WORDS:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)
    # Clean up double commas, extra spaces
    result = re.sub(r",\s*,+", ",", result)
    result = re.sub(r"\s+", " ", result)
    result = re.sub(r"\s+([,\.\?!])", r"\1", result).strip()
    return result


def validate_and_enforce_sync(
    keyframe_prompts: Dict[str, str],
    voiceover_text: str,
    mode: str = "physical",
) -> Dict[str, str]:
    """
    Validates that keyframe_prompts literally reflect the voiceover_text.
    If a mismatch or missing physical evidence is detected, injects specific visual cues.
    Also strips banned generic buzzwords.
    """
    if not keyframe_prompts or not voiceover_text:
        return keyframe_prompts

    vo_lower = voiceover_text.lower()

    start_prompt = (
        keyframe_prompts.get("start_prompt")
        or keyframe_prompts.get("start_frame_prompt")
        or ""
    )
    end_prompt = (
        keyframe_prompts.get("end_prompt")
        or keyframe_prompts.get("end_frame_prompt")
        or ""
    )
    motion_prompt = (
        keyframe_prompts.get("video_motion_prompt")
        or keyframe_prompts.get("motion_prompt")
        or ""
    )

    # Sanitize banned words first
    start_prompt = sanitize_banned_words(start_prompt)
    end_prompt = sanitize_banned_words(end_prompt)
    motion_prompt = sanitize_banned_words(motion_prompt)

    combined_prompts_lower = f"{start_prompt} {end_prompt} {motion_prompt}".lower()

    injections = []
    for keywords, rule in VOICEOVER_TO_VISUAL_MAP.items():
        # Check if voiceover triggers this concept
        triggered = any(kw in vo_lower for kw in keywords)
        if triggered:
            # Check if any required visual terms exist in the prompts
            has_term = any(rt in combined_prompts_lower for rt in rule["required_terms"])
            if not has_term:
                injections.append(rule["inject_desc"])

    # If injections needed, append to prompts
    if injections:
        injection_text = " " + " ".join(injections)

        # Insert before quality suffix if present
        suffix_marker = "No watermarks."
        if suffix_marker in start_prompt:
            start_prompt = start_prompt.replace(suffix_marker, f"{injection_text.strip()} {suffix_marker}")
        else:
            start_prompt += f" {injection_text.strip()}"

        if suffix_marker in end_prompt:
            end_prompt = end_prompt.replace(suffix_marker, f"{injection_text.strip()} {suffix_marker}")
        else:
            end_prompt += f" {injection_text.strip()}"

        # In motion prompt, append to RESULT or INITIAL STATE
        if "RESULT:" in motion_prompt:
            motion_prompt = motion_prompt.replace("RESULT:", f"RESULT: {injections[0]} ")
        else:
            motion_prompt += f" {injections[0]}"

    return {
        "start_prompt": start_prompt,
        "end_prompt": end_prompt,
        "video_motion_prompt": motion_prompt,
    }

