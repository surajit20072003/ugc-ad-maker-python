"""
pipeline/scene_engine.py
────────────────────────
"Dynamic Scenes" engine (video_backend == "heygen_scenes").

One self-contained path that builds a story ad out of HeyGen Video 1 clips:

  1. DIRECT    Claude writes 5-8 shots as JSON (dialogue, action, location, camera).
  2. REFERENCE One character image (uploaded avatar, or generated once) keeps the same
               person in every shot.
  3. GENERATE  One heygen/heygen-video-1 call per shot (reference image + scene prompt,
               the model speaks the dialogue itself). 768p -> 768x1344, no upscaling.
  4. CHECK     Audio present / not static; up to MAX_RETRIES retries with a new seed,
               bounded by SCENE_MAX_COST.
  5. ASSEMBLE  Trim each clip to the end of its speech, normalize loudness, concat.
  6. CAPTIONS  Bundled Poppins Bold (Latin + Devanagari) ASS captions, keywords in yellow.

Output: uploads/final_<job_id>.mp4 (same name pattern the other engines use).

Env (all optional):
  SCENE_SHOTS=6  SCENE_CONCURRENCY=3  SCENE_MAX_COST=6  SCENE_RESOLUTION=768p
  SCENE_LANGUAGE=<default language when no script is given; empty = English>  SCENE_VOICE_ID=<HeyGen voice id>
The page's language buttons (auto / English / Hinglish / Hindi) and voice picker override these per job.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import os
import random
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

import httpx
from dotenv import load_dotenv
from PIL import Image, ImageChops, ImageStat

from pipeline.video_gen import OPENROUTER_VIDEOS_URL, _image_to_data_url, _or_headers

load_dotenv()

CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
LLM_MODEL = "anthropic/claude-sonnet-5"
SCENE_MODEL = "heygen/heygen-video-1"

SCENE_RESOLUTION = os.getenv("SCENE_RESOLUTION", "768p")
OUT_W, OUT_H = 768, 1344                      # what 768p 9:16 produces; kept as-is (no upscale)
SHOT_COUNT = int(os.getenv("SCENE_SHOTS", "6"))
CONCURRENCY = int(os.getenv("SCENE_CONCURRENCY", "3"))
MAX_COST = float(os.getenv("SCENE_MAX_COST", "6"))
LANGUAGE = os.getenv("SCENE_LANGUAGE", "")      # default dialogue language when no script is given ("" = English)
VOICE_ID = os.getenv("SCENE_VOICE_ID", "")
MAX_RETRIES = 2
EST_CLIP_COST = 0.35                          # observed ~0.30 per 6s clip at 768p

BASE_DIR = Path(__file__).parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
FONTS_DIR = BASE_DIR / "static" / "fonts"
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8765").rstrip("/")

Emit = Callable[..., None]


# ─── 1. Director ─────────────────────────────────────────────────────────────

LANGUAGES = {"auto": "auto", "english": "English", "hinglish": "Hinglish", "hindi": "Hindi"}
SPEECH_PHRASE = {
    "English": "English",
    "Hindi": "Hindi",
    "Hinglish": "Hindi mixed with common English words (Hinglish)",
}


def _language_rule(language: str) -> str:
    low = language.lower()
    if "hinglish" in low:
        return ("Hinglish as Indian creators speak it: conversational Hindi written in Devanagari script, "
                "with common English words kept in Latin script (e.g. 'सर, ये कैसे possible है?').")
    if low == "hindi":
        return "Hindi written in Devanagari script."
    return f"{language}, conversational."


def detect_language(text: str) -> Optional[str]:
    """English / Hinglish / Hindi from the share of Devanagari letters (None if no letters)."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return None
    ratio = sum(1 for c in letters if "ऀ" <= c <= "ॿ") / len(letters)
    if ratio >= 0.6:
        return "Hindi"
    if ratio >= 0.1:
        return "Hinglish"
    return "English"


def resolve_language(choice: str, custom_script: str) -> tuple[str, bool]:
    """-> (language the ad is spoken in, translate_the_script).
    Auto follows the script's own language; with no script it is English unless SCENE_LANGUAGE is set.
    An explicit choice that differs from the script's language means: translate the script."""
    script_lang = detect_language(custom_script) if custom_script.strip() else None
    chosen = LANGUAGES.get((choice or "auto").strip().lower(), "auto")
    if chosen == "auto":
        return (script_lang or LANGUAGE or "English"), False
    return chosen, bool(script_lang and script_lang != chosen)


def split_script_lines(custom_script: str, max_words: int = 15, cap: int = 14) -> list[str]:
    """The user's script as spoken lines of <= ~max_words (one line = one shot), wording untouched."""
    from pipeline.script_split import parse_segments
    try:
        texts = [s["text"].strip() for s in parse_segments(custom_script) if str(s.get("text", "")).strip()]
    except Exception:
        texts = []
    if not texts:
        texts = [custom_script.strip()]
    lines: list[str] = []
    for t in texts:
        cur: list[str] = []
        for sent in [x.strip() for x in re.split(r"(?<=[.?!।])\s+", t) if x.strip()]:
            if cur and len(" ".join(cur + [sent]).split()) > max_words:
                lines.append(" ".join(cur))
                cur = []
            cur.append(sent)
        if cur:
            lines.append(" ".join(cur))
    out: list[str] = []
    for ln in lines:                                   # a single very long sentence: hard split
        w = ln.split()
        if len(w) <= max_words + 4:
            out.append(ln)
        else:
            out += [" ".join(w[i:i + max_words]) for i in range(0, len(w), max_words)]
    merged: list[str] = []
    for ln in out:                                     # fold tiny fragments into the previous line
        if merged and len(ln.split()) < 4:
            merged[-1] += " " + ln
        else:
            merged.append(ln)
    return merged[:cap]


DIRECTOR_SYSTEM = """You are a viral short-form ad director. You plan a vertical story ad as a list of SHOTS.
One person (the same character, from a reference photo) acts in every shot; each shot is generated by a text-and-reference-to-video model that also speaks the dialogue.

Rules:
- Arc: pain -> struggle -> discovery -> demo -> proof -> call to action. Fewer shots = compress the arc.
- ONE world: choose a single location for the whole ad (for example a bright modern office) and return it as "world". Every shot happens inside that world; "spot" is only the area within it (desk, laptop close-up, hallway, meeting corner). Never a home, outdoors or another building.
- Every shot is self-contained: ONE clear visible action, no cuts inside a shot. Vary the camera between shots (close-up, laptop close-up, over-the-shoulder, walking, to-camera...).
- Same character and same outfit in every shot. NEVER write actions that change, add or remove clothing, and never describe their clothes.
- Dialogue (when you write it): short, natural, spoken by the character; first shot hooks with the problem and does NOT name the product; last shot is a warm call to action that names the product. No stage directions inside dialogue. At most 1.5 words per second of duration (6s -> max 9 words).
- Write beat, emotion, action, spot, camera and world in ENGLISH (they go to a video model). Only dialogue uses the dialogue language.
- Actions are concrete and physical ("picks up the phone, frowns, lowers it and sighs"), never abstract.
- If a laptop/phone screen is in frame, say what plays on it (e.g. "an animated explainer video").
- caption_keywords: 1-2 single words copied EXACTLY from the dialogue that deserve yellow highlight.

Return ONLY JSON, no prose:
{"world":"...","shots":[{"beat":"hook","duration":6,"dialogue":"...","emotion":"stressed","action":"...","spot":"...","camera":"...","caption_keywords":["..."]}]}"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in director reply")
    return json.loads(text[start:end + 1])


def _normalize_shot(raw: dict, idx: int, world: str = "") -> dict:
    dialogue = str(raw.get("dialogue", "")).strip().strip('"')
    words = len(dialogue.split())
    duration = int(round(float(raw.get("duration", 6) or 6)))
    duration = max(duration, math.ceil(words / 1.6))     # make sure the line fits
    duration = max(5, min(15, duration))                 # model supports 5-15s
    kws = raw.get("caption_keywords") or []
    if isinstance(kws, str):
        kws = [kws]
    spot = str(raw.get("spot") or raw.get("location") or "").strip()
    return {
        "idx": idx,
        "beat": str(raw.get("beat", f"shot_{idx + 1}"))[:30],
        "duration": duration,
        "dialogue": dialogue,
        "emotion": str(raw.get("emotion", "natural"))[:40],
        "action": str(raw.get("action", "")).strip(),
        "location": ", ".join(x for x in (world, spot) if x),
        "camera": str(raw.get("camera", "")).strip(),
        # captions highlight single words, so split any phrase the director returns
        "caption_keywords": [w for k in kws for w in str(k).split() if _norm_word(w)][:4],
    }


async def direct_shots(
    product_name: str,
    product_benefit: str,
    mode: str,
    analysis: dict,
    language: str,
    n_shots: int,
    identity: str = "",
    lines: Optional[list[str]] = None,
    translate: bool = False,
) -> list[dict]:
    brief = {
        "product_name": product_name,
        "benefit": product_benefit,
        "mode": mode,
        "brand_name": analysis.get("brand_name"),
        "product_type": analysis.get("product_type"),
    }
    user = (
        f"Product brief: {json.dumps(brief, ensure_ascii=False)}\n"
        f"Character in the reference photo (fixed, never changes): {identity or 'as in the photo'}\n"
        f"Dialogue language: {_language_rule(language)}\n"
    )
    if lines:
        user += (
            f"MODE: FIXED DIALOGUE. The ad's spoken lines are given below, in order. Return exactly {len(lines)} shots, "
            "one per line, same order. Design the visible action, spot, camera, emotion, beat and caption_keywords "
            "for each line so the picture matches what is said.\n"
        )
        user += (
            "Also return \"dialogue\" for every shot: that line translated faithfully into the dialogue language above "
            "(keep every fact, number and brand name).\n"
            if translate else
            "Do NOT return dialogue; it is copied from the lines automatically.\n"
        )
        user += "Lines:\n" + "\n".join(f"{i + 1}. {ln}" for i, ln in enumerate(lines)) + "\n"
    else:
        user += f"Number of shots: {n_shots}\n"

    last_err: Optional[Exception] = None
    for _ in range(2):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    CHAT_URL,
                    headers=_or_headers(),
                    json={
                        "model": LLM_MODEL,
                        "messages": [{"role": "system", "content": DIRECTOR_SYSTEM},
                                     {"role": "user", "content": user}],
                        "temperature": 0.8,
                        "reasoning": {"effort": "low"},   # reasoning tokens count against max_tokens
                        "max_tokens": 8000,               # Devanagari dialogue is token-heavy
                    },
                )
                resp.raise_for_status()
                choice = resp.json()["choices"][0]
                content = choice["message"].get("content")
                if not content:
                    raise ValueError(f"empty director reply (finish_reason={choice.get('finish_reason')})")
                data = _extract_json(content)
            world = str(data.get("world") or "a bright modern office").strip()
            raw_shots = data.get("shots", [])
            if lines:                                    # dialogue comes from the user's lines, not the model
                shots = []
                for i, ln in enumerate(lines):
                    raw = raw_shots[i] if i < len(raw_shots) else {}
                    dlg = raw.get("dialogue") if (translate and raw.get("dialogue")) else ln
                    shots.append(_normalize_shot(
                        {**raw, "dialogue": dlg, "action": raw.get("action") or "talks to the camera while working at the desk"},
                        i, world))
                return shots
            shots = [_normalize_shot(s, i, world) for i, s in enumerate(raw_shots)]
            shots = [s for s in shots if s["action"]]
            if shots:
                return shots[: max(n_shots, 1) + 2]
            raise ValueError("director returned no usable shots")
        except Exception as e:  # retry once on bad JSON / transient error
            last_err = e
    raise RuntimeError(f"Story director failed: {last_err}")


# ─── 2. Prompt + reference ───────────────────────────────────────────────────

async def describe_reference(ref_data_url: str) -> str:
    """One short vision call: what the person in the reference photo looks like and wears ("" on failure)."""
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(CHAT_URL, headers=_or_headers(), json={
                "model": LLM_MODEL,
                "max_tokens": 1500,
                "reasoning": {"effort": "low"},
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": "Describe ONLY the person in this photo: gender, approximate age, hair, and their "
                                             "exact clothing (colors, fabric, accessories). One line, English, max 30 words. "
                                             "No background, no names."},
                    {"type": "image_url", "image_url": {"url": ref_data_url}},
                ]}],
            })
            resp.raise_for_status()
            text = (resp.json()["choices"][0]["message"].get("content") or "").strip().strip('"')
            return re.sub(r"\s+", " ", text)[:260]
    except Exception:
        return ""


def build_prompt(shot: dict, identity: str, language: str) -> str:
    who = f"The same person from the reference image ({identity})." if identity else "The same person from the reference image."
    parts = [
        f"{who} Exactly the same face, hair and clothing in every frame; do not change the outfit.",
        "Photorealistic, handheld smartphone-style vertical video, shallow depth of field, natural light.",
        f"Location: {shot['location'][:140]}." if shot["location"] else "",
        f"Camera: {shot['camera'][:90]}." if shot["camera"] else "",
        f"Action: {shot['action'][:260].rstrip('. ')}.",
        f"Emotion: {shot['emotion']}.",
    ]
    if shot["dialogue"]:
        parts.append(f'The person says in {SPEECH_PHRASE.get(language, language)}, naturally and clearly: "{shot["dialogue"]}"')
    parts.append("Natural ambient sound only, no music.")
    return " ".join(p for p in parts if p)


async def _reference_data_url(image_url: str) -> str:
    """Reference image as a compact JPEG data URL (long side <= 1280)."""
    data_url = await _image_to_data_url(image_url)
    raw = base64.b64decode(data_url.split(",", 1)[1])
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail((1280, 1280))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


# ─── 3. Generation + check ───────────────────────────────────────────────────

async def _submit(client: httpx.AsyncClient, payload: dict) -> dict:
    delay = 5
    for attempt in range(4):
        resp = await client.post(OPENROUTER_VIDEOS_URL, headers=_or_headers(), json=payload)
        if resp.status_code in (200, 202):
            return resp.json()
        if resp.status_code == 400 and ("seed" in payload or "provider" in payload):
            # optional extras rejected -> retry once with the bare payload
            payload = {k: v for k, v in payload.items() if k not in ("seed", "provider")}
            continue
        if resp.status_code in (429, 500, 502, 503) and attempt < 3:
            await asyncio.sleep(delay)
            delay *= 3
            continue
        raise RuntimeError(f"HeyGen Video submit failed ({resp.status_code}): {resp.text[:300]}")
    raise RuntimeError("HeyGen Video submit failed after retries")


async def _generate_clip(prompt: str, ref_data_url: str, duration: int, seed: int, out_path: Path,
                         voice_id: str = "") -> float:
    """Generate one clip -> out_path. Returns the reported cost (USD)."""
    payload: dict = {
        "model": SCENE_MODEL,
        "prompt": prompt,
        "aspect_ratio": "9:16",
        "duration": duration,
        "resolution": SCENE_RESOLUTION,
        "input_references": [{"type": "image_url", "image_url": {"url": ref_data_url}}],
        "seed": seed,
    }
    if voice_id:
        payload["provider"] = {"options": {"heygen": {"voice_id": voice_id}}}

    async with httpx.AsyncClient(timeout=60) as client:
        job = await _submit(client, payload)
        poll = job.get("polling_url") or f"{OPENROUTER_VIDEOS_URL}/{job['id']}"
        waited = 0
        while waited < 900:
            await asyncio.sleep(8)
            waited += 8
            pr = await client.get(poll, headers=_or_headers())
            if pr.status_code != 200:
                continue
            obj = pr.json()
            if obj.get("status") == "completed":
                urls = obj.get("unsigned_urls") or []
                if not urls:
                    raise RuntimeError(f"HeyGen Video completed without a URL: {obj}")
                dl = await client.get(urls[0], headers=_or_headers(), timeout=180)
                dl.raise_for_status()
                out_path.write_bytes(dl.content)
                return float((obj.get("usage") or {}).get("cost") or 0.0)
            if obj.get("status") == "failed":
                raise RuntimeError(f"HeyGen Video generation failed: {str(obj.get('error', obj))[:300]}")
    raise TimeoutError("HeyGen Video generation timed out")


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _duration(path: Path) -> float:
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _audio_mean_db(path: Path) -> Optional[float]:
    r = _run(["ffmpeg", "-v", "info", "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"])
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr)
    return float(m.group(1)) if m else None


def _motion_score(path: Path) -> float:
    """Mean abs grayscale difference between consecutive sampled frames (0-255)."""
    with tempfile.TemporaryDirectory() as td:
        _run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", "fps=3,scale=96:-1,format=gray",
              "-frames:v", "12", f"{td}/f_%02d.png"])
        frames = sorted(Path(td).glob("f_*.png"))
        if len(frames) < 2:
            return 0.0
        diffs = []
        prev = Image.open(frames[0])
        for f in frames[1:]:
            cur = Image.open(f)
            diffs.append(ImageStat.Stat(ImageChops.difference(prev, cur)).mean[0])
            prev = cur
        return sum(diffs) / len(diffs)


def check_clip(path: Path, has_dialogue: bool) -> tuple[bool, str]:
    if not path.exists() or path.stat().st_size < 10_000:
        return False, "file missing/too small"
    mean_db = _audio_mean_db(path)
    if mean_db is None:
        return False, "no audio track"
    if has_dialogue and mean_db < -45:
        return False, f"audio nearly silent ({mean_db:.0f} dB)"
    motion = _motion_score(path)
    if motion < 0.8:
        return False, f"almost static (motion {motion:.2f})"
    return True, f"ok (audio {mean_db:.0f} dB, motion {motion:.1f})"


# ─── 4. Assembly + captions ──────────────────────────────────────────────────

def _speech_window(path: Path, dur: float) -> tuple[float, float]:
    """(speech_start, speech_end) from silence detection; falls back to the full clip."""
    r = _run(["ffmpeg", "-v", "info", "-i", str(path), "-af", "silencedetect=n=-35dB:d=0.2", "-vn", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", r.stderr)]
    s0, s1 = 0.0, dur
    if starts and starts[0] <= 0.05 and ends:
        s0 = ends[0]
    if starts and (len(starts) > len(ends) or (ends and ends[-1] >= dur - 0.05)):
        s1 = starts[-1]
    if s1 - s0 < 0.5:                      # detection unreliable (ambience / no speech)
        return 0.0, dur
    return max(0.0, s0 - 0.05), s1


def _encode_clip(src: Path, dst: Path, trim_end: float) -> None:
    fade_start = max(0.0, trim_end - 0.04)
    vf = (f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease:flags=lanczos,"
          f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30")
    af = f"loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,afade=t=in:d=0.03,afade=t=out:st={fade_start:.3f}:d=0.04"
    r = _run(["ffmpeg", "-y", "-i", str(src), "-t", f"{trim_end:.3f}", "-vf", vf, "-af", af,
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(dst)])
    if r.returncode != 0:
        raise RuntimeError(f"clip encode failed: {r.stderr[-400:]}")


def _ass_time(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{(cs // 6000) % 60:02d}:{(cs // 100) % 60:02d}.{cs % 100:02d}"


def _norm_word(w: str) -> str:
    return re.sub(r"[^\w]", "", w, flags=re.UNICODE).lower()


def build_captions_ass(timeline: list[dict]) -> str:
    """
    timeline: [{offset, s0, s1, dialogue, keywords}] — one per kept clip (times in final video).
    Words are spread over the speech window by length; chunks of <=4 words, keywords in yellow.
    """
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {OUT_W}
PlayResY: {OUT_H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Poppins,56,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,60,60,430,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    for item in timeline:
        words = item["dialogue"].split()
        if not words:
            continue
        kw = {_norm_word(k) for k in item["keywords"]}
        t0 = item["offset"] + item["s0"]
        t1 = item["offset"] + item["s1"]
        weights = [len(w) + 1 for w in words]
        total = float(sum(weights))
        bounds, acc = [], 0.0
        for w in weights:
            bounds.append((t0 + (t1 - t0) * acc / total, t0 + (t1 - t0) * (acc + w) / total))
            acc += w
        # chunk: max 4 words, also break after sentence punctuation
        chunks, cur = [], []
        for i, w in enumerate(words):
            cur.append(i)
            if len(cur) >= 4 or re.search(r"[.?!।]$", w):
                chunks.append(cur)
                cur = []
        if cur:
            chunks.append(cur)
        for ch in chunks:
            start, end = bounds[ch[0]][0], bounds[ch[-1]][1]
            text = " ".join(
                (r"{\c&H0000D7FF&}" + words[i] + r"{\c&H00FFFFFF&}") if _norm_word(words[i]) in kw else words[i]
                for i in ch
            )
            text = r"{\fscx88\fscy88\t(0,110,\fscx100\fscy100)}" + text
            events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Cap,,0,0,0,,{text}")
    return header + "\n".join(events) + "\n"


def _burn_captions(video_in: Path, video_out: Path, ass_content: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".ass", delete=False, encoding="utf-8") as f:
        f.write(ass_content)
        ass_path = f.name
    try:
        esc = lambda p: str(p).replace("\\", "/").replace(":", "\\:")
        r = _run(["ffmpeg", "-y", "-i", str(video_in),
                  "-vf", f"ass='{esc(ass_path)}':fontsdir='{esc(FONTS_DIR)}'",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                  "-c:a", "copy", "-movflags", "+faststart", str(video_out)])
        if r.returncode != 0:
            raise RuntimeError(f"caption burn failed: {r.stderr[-400:]}")
    finally:
        try:
            os.unlink(ass_path)
        except OSError:
            pass


def assemble_video(clips: list[dict], job_id: str, captions: bool = True) -> Path:
    """clips: [{path, dialogue, keywords}] in order -> uploads/final_<job_id>.mp4"""
    work = UPLOAD_DIR / f"scene_work_{job_id}"
    work.mkdir(exist_ok=True)
    timeline, encoded, offset = [], [], 0.0
    for i, c in enumerate(clips):
        src: Path = c["path"]
        dur = _duration(src)
        s0, s1 = _speech_window(src, dur) if c["dialogue"] else (0.0, min(dur, 4.0))
        trim_end = min(dur, max(2.5, s1 + 0.35))
        dst = work / f"clip_{i}.mp4"
        _encode_clip(src, dst, trim_end)
        real = _duration(dst)
        encoded.append(dst)
        timeline.append({"offset": offset, "s0": s0, "s1": min(s1, real - 0.1), "dialogue": c["dialogue"],
                         "keywords": c["keywords"], "trim": real})
        offset += real

    listfile = work / "concat.txt"
    listfile.write_text("".join(f"file '{p.resolve()}'\n" for p in encoded))
    joined = work / "joined.mp4"
    r = _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile), "-c", "copy", str(joined)])
    if r.returncode != 0:
        raise RuntimeError(f"concat failed: {r.stderr[-400:]}")

    final = UPLOAD_DIR / f"final_{job_id}.mp4"
    if captions:
        _burn_captions(joined, final, build_captions_ass(timeline))
    else:
        joined.replace(final)
    for p in work.glob("*"):
        p.unlink(missing_ok=True)
    work.rmdir()
    return final


# ─── 5. Orchestrator ─────────────────────────────────────────────────────────

async def run_scene_engine(
    *,
    job_id: str,
    product_name: str,
    product_benefit: str,
    product_mode: str,
    analysis: dict,
    avatar_url: str,
    product_image_url: str,
    custom_script: str,
    ugc_image_model: str,
    image_provider: str,
    local_image_model: str,
    emit: Emit,
    voice_id: str = "",
    language_choice: str = "auto",
) -> dict:
    language, translate = resolve_language(language_choice, custom_script)
    voice_id = voice_id or VOICE_ID          # UI choice wins over the SCENE_VOICE_ID env default

    # Character reference ------------------------------------------------------
    ref_url = avatar_url
    if not ref_url:
        from pipeline.image_gen import generate_ugc_image, generate_ugc_prompt
        emit("image_gen", "Creating the character reference image (one time)...", 18)
        prompt = await generate_ugc_prompt(product_name, analysis, mode=product_mode, segment="hook", scene_direction=None)
        ref_url = await generate_ugc_image(
            prompt, product_image_url, model=ugc_image_model, job_id=f"{job_id}_ref",
            image_provider=image_provider, local_image_model=local_image_model,
        )
    else:
        emit("image_gen", "Using your character image as the reference for every shot.", 18)
    ref_data = await _reference_data_url(ref_url)

    # What the person in YOUR image looks like / wears (never the analysis step's invented profile)
    identity = await describe_reference(ref_data)
    emit("image_gen", f"Character locked from your image: {identity}" if identity
         else "⚠️ Could not read the outfit from the image; relying on the reference image alone.", 19)

    # Director -----------------------------------------------------------------
    lines = split_script_lines(custom_script) if custom_script.strip() else None
    n_shots = len(lines) if lines else SHOT_COUNT
    how = ("your script, " + ("translated" if translate else "word for word")) if lines else "written for you"
    emit("script", f"Directing a {n_shots}-shot story in {language} ({how})...", 20)
    shots = await direct_shots(product_name, product_benefit, product_mode, analysis, language, n_shots,
                               identity=identity, lines=lines, translate=translate)
    for s in shots:
        s["prompt"] = build_prompt(s, identity, language)
    (UPLOAD_DIR / f"scene_plan_{job_id}.json").write_text(json.dumps(shots, ensure_ascii=False, indent=1))
    emit("script", f"Story locked: {len(shots)} shots — " + ", ".join(s["beat"] for s in shots), 26)

    # Generate -----------------------------------------------------------------
    sem = asyncio.Semaphore(CONCURRENCY)
    state = {"cost": 0.0, "done": 0}
    n = len(shots)

    async def one(shot: dict) -> Optional[Path]:
        i = shot["idx"]
        path = UPLOAD_DIR / f"heygen_{job_id}_{i}.mp4"
        has_dialogue = bool(shot["dialogue"])
        if path.exists() and check_clip(path, has_dialogue)[0]:           # resume support
            state["done"] += 1
            return path
        best: Optional[Path] = None
        async with sem:
            for attempt in range(MAX_RETRIES + 1):
                if state["cost"] + EST_CLIP_COST > MAX_COST:
                    emit("video", f"⚠️ Shot {i + 1}: cost cap ${MAX_COST:.2f} reached, no more attempts.", 30 + int(50 * state["done"] / n))
                    break
                seed = random.randint(1, 2_000_000_000)
                tmp = UPLOAD_DIR / f"heygen_{job_id}_{i}_try{attempt}.mp4"
                try:
                    emit("video", f"🎬 Shot {i + 1}/{n} ({shot['beat']}): generating (attempt {attempt + 1})...", 30 + int(50 * state["done"] / n))
                    state["cost"] += await _generate_clip(shot["prompt"], ref_data, shot["duration"], seed, tmp, voice_id)
                except Exception as e:
                    emit("video", f"⚠️ Shot {i + 1} attempt {attempt + 1} failed: {e}", 30 + int(50 * state["done"] / n))
                    continue
                ok, why = check_clip(tmp, has_dialogue)
                emit("video", f"{'✅' if ok else '⚠️'} Shot {i + 1}: {why}", 30 + int(50 * state["done"] / n))
                best = tmp
                if ok:
                    break
        if best is None:
            return None
        best.replace(path)
        state["done"] += 1
        return path

    paths = await asyncio.gather(*[one(s) for s in shots])
    kept = [(s, p) for s, p in zip(shots, paths) if p is not None]
    if len(kept) < max(2, math.ceil(n / 2)):
        raise RuntimeError(f"Only {len(kept)}/{n} shots could be generated — aborting (spent ${state['cost']:.2f}).")
    emit("video", f"All shots ready ({len(kept)}/{n}). Generation cost ≈ ${state['cost']:.2f}", 82)

    # Assemble -----------------------------------------------------------------
    emit("compose", "Trimming, joining and adding captions...", 88)
    final = await asyncio.to_thread(
        assemble_video,
        [{"path": p, "dialogue": s["dialogue"], "keywords": s["caption_keywords"]} for s, p in kept],
        job_id,
        True,
    )

    segments = [{
        "label": f"scene_{s['idx'] + 1}",
        "text": s["dialogue"],
        "emotion": s["emotion"],
        "scene_type": "scene",
        "audio_duration_sec": float(s["duration"]),
        "scene_prompt": s["prompt"],
        "scene_direction": {
            "characters": "Same character as the reference image",
            "scene_background": s["location"],
            "camera_movement": s["camera"],
            "movement_in_scene": s["action"],
            "sound_design": "Native speech + natural ambience",
        },
    } for s, _ in kept]
    full = " ".join(s["dialogue"] for s, _ in kept)
    return {
        "video_url": f"{SERVER_URL}/uploads/{final.name}",
        "script": full,
        "raw_script": full,
        "display_script": "\n\n".join(f"[{s['beat'].upper()}] {s['dialogue']}" for s, _ in kept),
        "segments": segments,
        "clip_urls": [f"{SERVER_URL}/uploads/{p.name}" for _, p in kept],
        "ugc_image_url": ref_url,
        "audio_url": "",
        "cost": round(state["cost"], 3),
    }
