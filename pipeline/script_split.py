"""
pipeline/script_split.py
─────────────────────────
Parse scripts with arbitrary scenes:
  - Standard UGC 3-segment ([HOOK], [BODY], [CTA])
  - Multi-scene scripts (SCENE 1, SCENE 2, ... SCENE 5)
  - Numbered scenes (1}, 2}, 3} or [SCENE 1])
  - Combined with optional [SCENE_...] director notes

Maps each segment to:
  - spoken text (for VoxCPM TTS and SRT captions)
  - VoxCPM emotion key
  - structured scene direction dictionary
  - synthesized scene_prompt for video generation models
"""
from __future__ import annotations

import re
from typing import TypedDict, Optional


def _clean_spoken_text(text: str) -> str:
    """
    Strip non-speech content that the LLM or user injects inline with dialogue before
    the text reaches the TTS engine.

    Removes:
    - Parenthetical stage directions: (leaning in), (whispering)
    - Asterisk action markers / markdown: *pauses*, *gestures at camera*, **bold**
    - Bracketed emotion/action tags: [excited], [pause], [hook]
    - Angle-bracket tags: <encourage>, <emotion: hook>
    - Director key lines that bled through: 'Camera: slow zoom', 'Sound Design: ...'
    - Header lines that bled through: 'HOOK | 0-8s', 'CTA: ...'
    - Stray timestamp fragments: '0-8 seconds', '0:00 - 0:08'
    - Smart/curly quotes & straight quotes that become spoken verbatim
    - Replaces inline em/en dashes with comma for natural speech rhythm
    """
    # Remove parenthetical stage directions (up to ~200 chars)
    text = re.sub(r'\([^)]{0,200}\)', '', text)
    # Remove asterisk action markers
    text = re.sub(r'\*[^*]{0,200}\*', '', text)
    # Remove bracketed short tags (emotion / action labels, NOT scene headers)
    text = re.sub(r'\[[a-zA-Z][a-zA-Z0-9_ ]{0,40}\]', '', text)
    # Remove angle-bracket tags
    text = re.sub(r'<[a-zA-Z][a-zA-Z0-9_: ]{0,40}>', '', text)
    # Remove director key lines that bled through (case-insensitive, full line)
    _DIRECTOR_KEYS = (
        r'visual type|characters|scene background|background|camera movement'
        r'|camera|movement in scene|movement|sound design|kling prompt'
        r'|kling motion|start frame|end frame'
    )
    text = re.sub(
        rf'^(?:{_DIRECTOR_KEYS})\s*:.*$',
        '',
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    # Remove scene header/label lines that bled through (e.g. HOOK | 0-8s)
    text = re.sub(
        r'^(?:[\*\#\-\s_~|—–]*)(?:HOOK|PROBLEM|BENEFITS?|EXPERIENCE|CTA|SOLUTION|OUTRO|INTRO)\b[^\n]*$',
        '',
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    # Strip standalone timestamps
    text = re.sub(r'\b\d+\s*[-–—]\s*\d+\s*(?:sec(?:onds)?|s)\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b\d+:\d{2}\s*[-–—]\s*\d+:\d{2}\b', '', text)
    # Normalize quotes
    text = text.replace('\u201c', '').replace('\u201d', '')
    text = text.replace('\u2018', '').replace('\u2019', "'")
    text = text.replace('"', '')
    # Strip markdown symbols
    text = text.replace('*', '').replace('#', '').replace('~', '')
    # Replace inline em/en-dashes with comma for natural speech pauses
    text = re.sub(r'\s*[\u2014\u2013]\s*', ', ', text)
    text = re.sub(r'-{2,}', ', ', text)
    # Clean leading/trailing punctuation/dashes/pipes/colons
    text = re.sub(r'^[\s,.:|;—–\-]+', '', text)
    text = re.sub(r'[\s|—–\-]+$', '', text)
    # Collapse multiple spaces / newlines to single space
    text = re.sub(r'\n+', ' ', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    # Clean double commas if any
    text = re.sub(r',\s*,', ',', text)
    return text.strip()


class Segment(TypedDict, total=False):
    label: str               # "hook" | "body" | "cta" | "scene_1" ...
    text: str                # spoken dialogue only (for TTS & captions)
    emotion: str             # VoxCPM emotion key
    scene_type: str          # "avatar" | "b_roll"
    kling_prompt: str        # tailored prompt for Kling AI B-Roll
    scene_prompt: str        # combined visual scene prompt for video models
    scene_direction: dict    # detailed breakdown (characters, background, camera, movement, sound, visual_type, kling_prompt)
    audio_duration_sec: float# measured audio length in seconds


def _parse_scene_block(scene_text: str) -> dict:
    """Parse key: value lines from a [SCENE_...] block.
    Supports both legacy single-field Kling Prompt and new 3-field format:
      Kling Prompt Start Frame, Kling Prompt End Frame, Kling Motion Prompt
    """
    direction = {
        "visual_type": "",
        "kling_prompt": "",           # legacy / combined
        "kling_prompt_start": "",     # new: opening frame description
        "kling_prompt_end": "",       # new: closing frame description
        "kling_motion_prompt": "",    # new: motion/camera description
        "characters": "",
        "scene_background": "",
        "camera_movement": "",
        "movement_in_scene": "",
        "sound_design": "",
    }
    current_key = None
    for line in scene_text.splitlines():
        line_s = line.strip()
        if not line_s:
            continue
        lower_line = line_s.lower()
        if lower_line.startswith("visual type:") or lower_line.startswith("type:"):
            current_key = "visual_type"
            val = line_s.split(":", 1)[1].strip().lower()
            direction[current_key] = "b_roll" if "b_roll" in val or "broll" in val else "avatar"
        # New 3-field format (check before legacy "kling prompt:" to avoid prefix collision)
        elif lower_line.startswith("kling prompt start frame:") or lower_line.startswith("kling start frame:"):
            current_key = "kling_prompt_start"
            direction[current_key] = line_s.split(":", 1)[1].strip()
        elif lower_line.startswith("kling prompt end frame:") or lower_line.startswith("kling end frame:"):
            current_key = "kling_prompt_end"
            direction[current_key] = line_s.split(":", 1)[1].strip()
        elif lower_line.startswith("kling motion prompt:") or lower_line.startswith("kling motion:"):
            current_key = "kling_motion_prompt"
            direction[current_key] = line_s.split(":", 1)[1].strip()
        # Legacy single-field format
        elif lower_line.startswith("kling prompt:") or lower_line.startswith("kling:") or lower_line.startswith("b_roll prompt:"):
            current_key = "kling_prompt"
            direction[current_key] = line_s.split(":", 1)[1].strip()
        elif lower_line.startswith("characters:"):
            current_key = "characters"
            direction[current_key] = line_s.split(":", 1)[1].strip()
        elif lower_line.startswith("scene background:") or lower_line.startswith("background:"):
            current_key = "scene_background"
            direction[current_key] = line_s.split(":", 1)[1].strip()
        elif lower_line.startswith("camera movement:") or lower_line.startswith("camera:"):
            current_key = "camera_movement"
            direction[current_key] = line_s.split(":", 1)[1].strip()
        elif lower_line.startswith("movement in scene:") or lower_line.startswith("movement:"):
            current_key = "movement_in_scene"
            direction[current_key] = line_s.split(":", 1)[1].strip()
        elif lower_line.startswith("sound design:") or lower_line.startswith("sound:"):
            current_key = "sound_design"
            direction[current_key] = line_s.split(":", 1)[1].strip()
        elif current_key:
            direction[current_key] += " " + line_s

    # Synthesise combined kling_prompt from 3-field format for backward compatibility
    if not direction["kling_prompt"] and direction["kling_prompt_start"]:
        direction["kling_prompt"] = (
            f"{direction['kling_prompt_start']} "
            f"Transition to: {direction['kling_prompt_end']} "
            f"Motion: {direction['kling_motion_prompt']}"
        ).strip()

    return direction


def parse_segments(script: str) -> list[Segment]:
    """
    Parse a script into an ordered list of Segment objects.
    Supports:
      - 3-segment [HOOK], [BODY], [CTA]
      - Multi-scene SCENE 1, SCENE 2, ... SCENE 5 (with optional timestamps like — 0-8 SEC)
      - Numbered scenes (1}, 2}, 3})
    """
    clean_script = script.strip()
    if not clean_script:
        return []

    # 0. Check for multi-ad document containing numbered variations (e.g. 1} SCENE 1 ..., 2} SCENE 1 ...)
    variation_pattern = re.compile(
        r'(?:\n|^)\s*(?=\d+[\]\}\)]\s*SCENE\s*1\b|\bAD\s*\d+\b|\bVARIATION\s*\d+\b)',
        re.IGNORECASE
    )
    parts = [p.strip() for p in variation_pattern.split(clean_script) if p.strip()]
    if len(parts) > 1:
        print(f"[SCRIPT_SPLIT] Multiple ad variations detected ({len(parts)} ads). Processing Variation 1 (Scenes 1-5).", flush=True)
        clean_script = parts[0]

    # 1. Check for SCENE 1..N or [SCENE 1..N] (supports markdown *, **, #, timestamps, etc.)
    scene_pattern = re.compile(
        r'(?:^|\n)[ \t*#_~—–]*(?:\[?\s*SCENE\s*(\d+)[^\n\]]*\]?|(\d+)[}\)]\s*SCENE\s*(\d+)[^\n]*|\bSCENE\s*(\d+)[^\n]*)[ \t*#_~—–]*(?:\r?\n|$)',
        re.IGNORECASE
    )
    scene_matches = list(scene_pattern.finditer(clean_script))

    if len(scene_matches) >= 2:
        return _parse_numbered_scenes(clean_script, scene_matches)

    # 2. Check for [HOOK], [BODY], [CTA]
    hook_body_cta_pattern = re.compile(r'\[(HOOK|BODY|CTA)\]', re.IGNORECASE)
    hbc_matches = list(hook_body_cta_pattern.finditer(clean_script))
    if hbc_matches:
        return _parse_hook_body_cta(clean_script)

    # 3. Fallback: single segment
    return [{
        "label": "body",
        "text": clean_script,
        "emotion": "encourage",
        "scene_prompt": clean_script,
        "scene_direction": {},
    }]


def _parse_numbered_scenes(script: str, matches: list[re.Match]) -> list[Segment]:
    """Parse SCENE 1 ... SCENE N format."""
    segments: list[Segment] = []
    total_scenes = len(matches)

    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(script)
        scene_raw = script[start:end].strip()

        # Clean timestamps or labels like "— 0–8 SEC", quotes, etc.
        lines = []
        scene_dir_text = ""
        in_scene_dir = False

        for line in scene_raw.splitlines():
            line_s = line.strip()
            if not line_s:
                continue
            if re.match(r'^\[SCENE_.*\]', line_s, re.IGNORECASE):
                in_scene_dir = True
                continue
            if in_scene_dir:
                scene_dir_text += line_s + "\n"
            else:
                # Discard lines that are pure headers or stage labels
                if re.match(r'^(?:[\*\#\-\s_~|—–]*)(?:SCENE\s*\d+|HOOK|PROBLEM|BENEFITS?|EXPERIENCE|CTA|SOLUTION|OUTRO|INTRO)\b', line_s, re.IGNORECASE):
                    quote_m = re.search(r'["“](.+?)["”]', line_s)
                    if quote_m:
                        lines.append(quote_m.group(1))
                    continue
                # Discard standalone timestamp lines like "0-8 seconds" or "| 0–8 seconds*"
                if re.match(r'^[\*\s|—–-]*\d+[\s–-]+\d+\s*(?:sec(?:onds)?|s)?[\*\s]*$', line_s, re.IGNORECASE):
                    continue
                lines.append(line_s)

        spoken_text = _clean_spoken_text(" ".join(lines))
        if not spoken_text:
            continue

        scene_idx = i + 1
        label = f"scene_{scene_idx}"
        if scene_idx == 1:
            label = "hook"
            emotion = "hook"
        elif scene_idx == total_scenes:
            label = "cta"
            emotion = "excited"
        else:
            emotion = "explain" if scene_idx == 2 else "encourage"

        scene_dir = _parse_scene_block(scene_dir_text) if scene_dir_text else {}
        
        # Determine scene type: avatar vs b_roll
        explicit_type = scene_dir.get("visual_type")
        if explicit_type in ("avatar", "b_roll"):
            scene_type = explicit_type
        else:
            # Default heuristic for hybrid: 1 is hook (avatar), last is cta (avatar), middle are b_roll
            scene_type = "avatar" if (scene_idx == 1 or scene_idx == total_scenes) else "b_roll"

        kling_prompt = scene_dir.get("kling_prompt", "")
        if not kling_prompt and scene_type == "b_roll":
            bg = scene_dir.get("scene_background", "modern aesthetic studio")
            mov = scene_dir.get("movement_in_scene", "product demonstration")
            kling_prompt = f"Cinematic b-roll macro shot: {mov} in {bg}, clean unbranded surface, no visible text or labels, shallow depth of field, dramatic lighting, vertical 9:16 format, photorealistic 4k"

        # Build prompt
        if scene_dir.get("characters") or scene_dir.get("movement_in_scene"):
            components = []
            if scene_dir.get("characters"): components.append(scene_dir["characters"])
            if scene_dir.get("scene_background"): components.append(f"in {scene_dir['scene_background']}")
            if scene_dir.get("movement_in_scene"): components.append(scene_dir["movement_in_scene"])
            if scene_dir.get("camera_movement"): components.append(f"camera {scene_dir['camera_movement']}")
            scene_prompt = ". ".join(components)
        else:
            scene_prompt = f"UGC creator speaking directly to camera for {label}: {spoken_text}"

        segments.append({
            "label": label,
            "text": spoken_text,
            "emotion": emotion,
            "scene_type": scene_type,
            "kling_prompt": kling_prompt,
            "scene_prompt": scene_prompt,
            "scene_direction": scene_dir,
            "audio_duration_sec": 0.0,
        })

    return segments


def _parse_hook_body_cta(script: str) -> list[Segment]:
    """Parse traditional [HOOK], [BODY], [CTA] tags."""
    labels = ["hook", "body", "cta"]
    emotions = {"hook": "hook", "body": "encourage", "cta": "excited"}
    segments: list[Segment] = []

    for label in labels:
        spoken_tag = f"[{label}]"
        scene_tag = f"[SCENE_{label}]"
        
        stop_tags = [scene_tag, "[HOOK]", "[BODY]", "[CTA]", "[SCENE_HOOK]", "[SCENE_BODY]", "[SCENE_CTA]"]
        stop_tags = [t for t in stop_tags if t.upper() != spoken_tag.upper()]
        
        idx = script.upper().find(spoken_tag.upper())
        if idx == -1:
            continue
        start_pos = idx + len(spoken_tag)
        rem = script[start_pos:]
        
        earliest_stop = len(rem)
        for tag in stop_tags:
            p = rem.upper().find(tag.upper())
            if p != -1 and p < earliest_stop:
                earliest_stop = p
        spoken_text = _clean_spoken_text(rem[:earliest_stop])

        # Extract scene tag if present
        sidx = script.upper().find(scene_tag.upper())
        scene_dir = {}
        if sidx != -1:
            s_rem = script[sidx + len(scene_tag):]
            s_earliest = len(s_rem)
            for tag in ["[HOOK]", "[BODY]", "[CTA]"]:
                sp = s_rem.upper().find(tag.upper())
                if sp != -1 and sp < s_earliest:
                    s_earliest = sp
            scene_dir = _parse_scene_block(s_rem[:s_earliest].strip())

        if spoken_text:
            explicit_type = scene_dir.get("visual_type")
            if explicit_type in ("avatar", "b_roll"):
                scene_type = explicit_type
            else:
                scene_type = "avatar" if label in ("hook", "cta") else "b_roll"

            kling_prompt = scene_dir.get("kling_prompt", "")
            if not kling_prompt and scene_type == "b_roll":
                bg = scene_dir.get("scene_background", "clean aesthetic studio")
                mov = scene_dir.get("movement_in_scene", "product demonstration")
                kling_prompt = f"Cinematic close-up product b-roll: {mov} in {bg}, clean minimalist unbranded packaging, no visible text, realistic lighting, slow smooth camera glide, 9:16 vertical video, 4k"

            components = []
            if scene_dir.get("characters"): components.append(scene_dir["characters"])
            if scene_dir.get("scene_background"): components.append(f"in {scene_dir['scene_background']}")
            if scene_dir.get("movement_in_scene"): components.append(scene_dir["movement_in_scene"])
            if scene_dir.get("camera_movement"): components.append(f"camera {scene_dir['camera_movement']}")
            scene_prompt = ". ".join(components) if components else spoken_text

            segments.append({
                "label": label,
                "text": spoken_text,
                "emotion": emotions.get(label, "neutral"),
                "scene_type": scene_type,
                "kling_prompt": kling_prompt,
                "scene_prompt": scene_prompt,
                "scene_direction": scene_dir,
                "audio_duration_sec": 0.0,
            })

    order = {"hook": 0, "body": 1, "cta": 2}
    segments.sort(key=lambda s: order.get(s["label"], 99))
    return segments


def segments_to_full_script(segments: list[Segment]) -> str:
    """Reconstruct full plain spoken script from segments."""
    return " ".join(s["text"] for s in segments)


def format_script_for_display(script: str) -> str:
    """Format the raw script with its scene headers into clean display text."""
    output = []
    lines = script.splitlines()
    for line in lines:
        s = line.strip()
        if re.match(r'^(?:\[?SCENE\s*(\d+).*|\bSCENE\s*(\d+)\b)', s, re.IGNORECASE):
            output.append(f"\n🎬 {s}")
        elif re.match(r'^\[HOOK\]$', s, re.IGNORECASE):
            output.append("\n🎬 [HOOK] (👤 Creator Avatar)")
        elif re.match(r'^\[BODY\]$', s, re.IGNORECASE):
            output.append("\n🎥 [BODY] (🎬 Kling Cinematic B-Roll)")
        elif re.match(r'^\[CTA\]$', s, re.IGNORECASE):
            output.append("\n🚀 [CALL TO ACTION] (👤 Creator Avatar)")
        elif re.match(r'^\[SCENE_(.*)\]$', s, re.IGNORECASE):
            output.append("\n🎥 Director Visual Breakdown:")
        elif s:
            output.append(s)
    return "\n".join(output).strip()
