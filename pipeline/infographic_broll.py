"""
pipeline/infographic_broll.py
─────────────────────────────
Infographic image-to-video B-roll that visually represents the voiceover.

Per B-roll scene:
  1. Storyboard   – Claude splits the voiceover into phrase beats, each with a literal
                    visual metaphor, exact on-screen labels and start/end states.
  2. Keyframes    – Gemini image model renders a true 9:16 start frame per beat; the end
                    frame is an EDIT of the start frame (identical layout, changed state).
                    Every frame is vision-checked (label spelling + concept) and retried.
  3. Image→video  – Veo 3.1 animates start→end per beat (locked camera, no audio).
  4. Assembly     – beats are time-fitted to the measured speech and muxed with the WAV.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import os
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from PIL import Image

from pipeline.broll_gen import generate_kling_broll
from pipeline.scene_composer import compose_beat_scene, get_media_duration
from pipeline.word_align import phrase_durations

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
LLM_MODEL = "anthropic/claude-sonnet-5"
IMAGE_MODEL = os.getenv("INFOGRAPHIC_IMAGE_MODEL", "openai/gpt-image-2")
GPT_IMAGE_QUALITY = os.getenv("GPT_IMAGE_QUALITY", "medium")
IMAGES_URL = "https://openrouter.ai/api/v1/images"
IMAGE_FALLBACK = "google/gemini-3.1-flash-image"
VIDEO_MODEL = os.getenv("INFOGRAPHIC_VIDEO_MODEL", "bytedance/seedance-1-5-pro")
VIDEO_RESOLUTION = os.getenv("INFOGRAPHIC_VIDEO_RESOLUTION", "720p")
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8765").rstrip("/")
UPLOAD_DIR = Path(__file__).parent.parent / "uploads"

FRAME_W, FRAME_H = 1080, 1920
MAX_FRAME_ATTEMPTS = 3
IMAGE_CONCURRENCY = 4
VIDEO_CONCURRENCY = 4

LogFn = Callable[[str], None]


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8765",
        "X-Title": "UGC Ad Maker Infographic B-Roll",
    }


# ─── Style bible ─────────────────────────────────────────────────────────────

def build_style_bible(analysis: dict, product_name: str) -> str:
    colors = analysis.get("color_scheme") or []
    names = [f"{c.get('name', '')} {c.get('hex', '')}".strip() for c in colors if isinstance(c, dict)]
    primary = names[0] if names else "electric blue #2563EB"
    secondary = names[1] if len(names) > 1 else "cool white #F8FAFC"
    return (
        "VISUAL SYSTEM (must be identical in every frame of the ad):\n"
        "- Vertical 9:16 flat-vector infographic with subtle soft depth and glow. Premium tech-ad look. "
        "No photographs of people, no stock-photo look.\n"
        f"- Background: deep dark navy-charcoal with a soft radial glow in the primary accent. Primary accent: {primary}. "
        f"Secondary accent: {secondary}. Negative/problem states use red #EF4444, positive/success states use green #22C55E.\n"
        "- Typography: heavy condensed bold sans-serif, white, ALL CAPS. Headline label in the top third, "
        "supporting badge in the lower third. Maximum 3 text elements per frame, each at most 4 words, always large and bold. "
        "No small print, no paragraphs.\n"
        "- Layout: 8% safe margins; headline y 8-20%; main illustration centered y 25-75%; badge or stat y 78-90%.\n"
        "- Icons: rounded flat icons with consistent stroke weight and the same corner radius across frames.\n"
        f"- Brand: {analysis.get('brand_name', product_name)}. Do not draw real third-party logos."
    )


# ─── Storyboard ──────────────────────────────────────────────────────────────

STORYBOARD_SYSTEM = """You are an infographic ad director. You turn ONE spoken voiceover segment into a storyboard of beats for a vertical short-form ad.
Each beat is a still illustrated frame pair (start frame -> end frame) that an image-to-video model will animate.

RULES
1. PARTITION: split the voiceover into exactly N consecutive phrases that together contain every word, in order. Put the exact words of each phrase in "phrase".
   Balance the phrases by spoken length (roughly equal word counts). Each beat covers at most TWO closely related ideas, so every idea gets its own clear visual; never cram a list of four things into one beat.
2. LITERAL VISUALS: the beat must show a literal, concrete visual metaphor of what that phrase says, understandable with the sound off.
   Examples: "slow loading" -> browser window with spinner and progress bar stuck at 38%; "weak security" -> padlock hanging open with a red warning badge;
   "save money" -> two price tags, the old one crossed out, the new one lower; "three steps" -> numbered 1-2-3 flow.
   Never use a generic laptop or a generic product shot unrelated to the words.
3. LABELS: 1-3 on-screen labels per beat, each at most 4 words, ALL CAPS, taken from or directly paraphrasing the spoken words. Labels stay IDENTICAL in the start and end frame.
   Only invent numbers if the voiceover or product info states them; otherwise use neutral states (e.g. progress bars) with no fabricated statistics.
4. START vs END STATE: the end frame is an edit of the start frame. Describe the single clear change (bar fills, icon flips from red to green, counter rises, element appears).
   Same layout, same background, same camera. Only the state changes, but the change must be OBVIOUS at a glance: at least two visible elements change
   (e.g. a color flips red<->green, a large icon appears or disappears, a bar fills, an element moves). A single small icon appearing is NOT enough.
   TEXT NEVER CHANGES: every word and number on screen must be IDENTICAL in the start and end frame (same spelling, same digits, same position). Video models corrupt changing text, so show change only through shapes, bars, colors and icons; any number shown is a fixed label such as '38%' that never updates.
5. MOTION: one sentence describing exactly what moves between start and end and in what order. Camera is locked.
6. LAYOUT must be one of: stat_counter, before_after, checklist, three_step_flow, chart, icon_grid, timeline, device_ui, comparison_panel.
7. "show_product": true only if the physical product itself must appear (physical-product ads), else false.
8. No brand logos of third parties. No people.

Return ONLY JSON: {"beats":[{"phrase":"...","concept":"...","layout":"...","labels":["..."],"start_state":"...","end_state":"...","motion":"...","show_product":false}]}"""


async def _llm_json(system: str, user: str, max_tokens: int = 2500, temperature: float = 0.5) -> dict:
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(CHAT_URL, headers=_headers(), json=payload)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    return json.loads(cleaned[start:end + 1])


def _plan_beat_count(duration: float) -> int:
    return max(1, min(5, max(math.ceil(duration / 8.0), math.ceil(duration / 3.2))))


def _even_phrases(text: str, n: int) -> List[str]:
    words = text.split()
    size = max(1, math.ceil(len(words) / n))
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)][:n]


async def build_storyboard(
    voiceover: str,
    duration: float,
    analysis: dict,
    product_name: str,
    mode: str,
    scene_hint: str,
    wav_path: Path,
) -> List[dict]:
    n = _plan_beat_count(duration)
    ctx = (
        f"Product: {product_name}. Brand: {analysis.get('brand_name', product_name)}. Mode: {mode}. "
        f"Type: {analysis.get('product_type', '')}. Use case: {analysis.get('use_case', '')}. "
        f"Audience: {analysis.get('audience', '')}. Look: {analysis.get('visual_description', '')}."
    )
    user = (
        f"N = {n} beats.\nSEGMENT DURATION: {duration:.1f}s\nPRODUCT INFO: {ctx}\n"
        f"DIRECTOR HINT (may be vague, optional): {scene_hint[:500]}\n\nVOICEOVER:\n{voiceover}"
    )
    beats: List[dict] = []
    for _ in range(2):
        try:
            data = await _llm_json(STORYBOARD_SYSTEM, user)
            cand = [b for b in data.get("beats", []) if isinstance(b, dict) and b.get("phrase")]
            if len(cand) == n and all(b.get("labels") and b.get("start_state") and b.get("end_state") for b in cand):
                beats = cand
                break
            elif len(cand) >= 1 and all(b.get("start_state") and b.get("end_state") for b in cand):
                beats = cand[:n]
                break
        except Exception:
            continue
    if not beats:
        phrases = _even_phrases(voiceover, n)
        beats = [
            {
                "phrase": p,
                "concept": f"{product_name} visual presentation - {p[:30]}",
                "layout": "device_ui",
                "start_state": f"Graphic illustration demonstrating {p[:40]}",
                "end_state": f"Dynamic updated state showing {p[:40]}",
                "motion": f"Fluid vector motion for {p[:40]}",
                "labels": [product_name.upper()[:20]],
                "show_product": True,
            }
            for p in phrases
        ]

    durs = phrase_durations(voiceover, [b["phrase"] for b in beats], wav_path, duration)
    if max(durs) > 8.0 or len(durs) != len(beats):
        durs = [round(duration / len(beats), 3)] * len(beats)
    for b, d in zip(beats, durs):
        b["duration"] = d
        b["labels"] = [str(x).upper()[:40] for x in (b.get("labels") or [])][:3]
    return beats


# ─── Image generation, normalization, vision QA ──────────────────────────────

def _to_data_url(path: Path, max_side: Optional[int] = None) -> str:
    img = Image.open(path).convert("RGB")
    if max_side:
        img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _save_normalized(data: bytes, dest: Path) -> Path:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    scale = max(FRAME_W / img.width, FRAME_H / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left = (img.width - FRAME_W) // 2
    top = (img.height - FRAME_H) // 2
    img = img.crop((left, top, left + FRAME_W, top + FRAME_H))
    img.save(dest, "JPEG", quality=95, subsampling=0)
    return dest


async def _images_endpoint_call(model: str, parts: list) -> bytes:
    """OpenAI-style image models only work on /api/v1/images (text prompt + input_references for edits)."""
    prompt = "\n".join(p["text"] for p in parts if p.get("type") == "text")
    refs = [p for p in parts if p.get("type") == "image_url"]
    payload = {"model": model, "prompt": prompt, "aspect_ratio": "9:16", "quality": GPT_IMAGE_QUALITY}
    if refs:
        payload["input_references"] = refs
    async with httpx.AsyncClient(timeout=400) as client:
        resp = await client.post(IMAGES_URL, headers=_headers(), json=payload)
    if resp.status_code != 200:
        raise RuntimeError(f"{resp.status_code} {resp.text[:200]}")
    entry = resp.json()["data"][0]
    if entry.get("b64_json"):
        return base64.b64decode(entry["b64_json"])
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.get(entry["url"])
        r.raise_for_status()
        return r.content


async def _image_call(parts: list, model: str = "") -> bytes:
    primary = model or IMAGE_MODEL
    last_err = "unknown"
    for attempt in range(MAX_FRAME_ATTEMPTS):
        use = primary if attempt < 2 else IMAGE_FALLBACK
        try:
            if use.startswith("openai/"):
                return await _images_endpoint_call(use, parts)
            image_config = {"aspect_ratio": "9:16"}
            if use == "google/gemini-3-pro-image":
                image_config["image_size"] = "2K"
            payload = {
                "model": use,
                "modalities": ["image", "text"],
                "image_config": image_config,
                "messages": [{"role": "user", "content": parts}],
            }
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(CHAT_URL, headers=_headers(), json=payload)
            if resp.status_code != 200:
                last_err = f"{resp.status_code} {resp.text[:200]}"
            else:
                msg = resp.json()["choices"][0]["message"]
                imgs = msg.get("images") or []
                if imgs:
                    url = imgs[0]["image_url"]["url"]
                    return base64.b64decode(url.split(",", 1)[1])
                last_err = "no image in response"
        except Exception as exc:
            last_err = str(exc)
        await asyncio.sleep(3)
    raise RuntimeError(f"Image generation failed: {last_err}")


async def _qa_frame(path: Path, labels: List[str], concept: str) -> dict:
    prompt = (
        "You are a strict QA reviewer for an infographic ad frame (vertical 9:16).\n"
        f"Intended concept: {concept}\n"
        f"Text that must appear EXACTLY (spelled exactly, no other text): {json.dumps(labels)}\n"
        "Check: (1) every required label is present and spelled exactly, with no garbled or extra text; "
        "(2) the illustration clearly shows the concept; (3) nothing is cropped or overlapping badly.\n"
        'Return ONLY JSON: {"ok": true|false, "issues": "short description of problems or empty"}'
    )
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": _to_data_url(path, 900)}},
        ]}],
        "temperature": 0.0,
        "max_tokens": 300,
    }
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(CHAT_URL, headers=_headers(), json=payload)
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned[cleaned.find("{"):cleaned.rfind("}") + 1])
    except Exception:
        return {"ok": True, "issues": ""}


async def _make_frame(
    dest: Path,
    build_parts: Callable[[str], list],
    labels: List[str],
    concept: str,
    log: LogFn,
    model: str = "",
    image_provider: str = "local",
    local_image_model: str = "flux_dev",
) -> Path:
    if image_provider == "local":
        try:
            from pipeline.local_gpu_client import LocalGPUClient, generate_image_async
            gpu_client = LocalGPUClient()
            if gpu_client.is_available():
                parts = build_parts("")
                prompt_texts = [p["text"] for p in parts if isinstance(p, dict) and p.get("type") == "text" and p.get("text")]
                prompt = "\n".join(prompt_texts) if prompt_texts else concept
                log(f"🖥️ Generating frame via Local GPU ({local_image_model}): {dest.name}")
                local_res = await generate_image_async(
                    client=gpu_client,
                    prompt=prompt,
                    output_path=str(dest),
                    model=local_image_model or "flux_dev",
                )
                if local_res and Path(local_res).exists() and Path(local_res).stat().st_size > 1000:
                    return _save_normalized(Path(local_res).read_bytes(), dest)
                log(f"⚠️ Local GPU image gen failed, falling back to cloud for {dest.name}...")
            else:
                log(f"⚠️ Local GPU server unavailable, falling back to cloud for {dest.name}...")
        except Exception as local_err:
            log(f"⚠️ Local GPU error ({local_err}), falling back to cloud for {dest.name}...")

    issues = ""
    last: Optional[Path] = None
    for attempt in range(MAX_FRAME_ATTEMPTS):
        data = await _image_call(build_parts(issues), model)
        last = _save_normalized(data, dest)
        qa = await _qa_frame(last, labels, concept)
        if qa.get("ok"):
            return last
        issues = str(qa.get("issues", ""))[:300]
        log(f"🔍 Frame QA retry {attempt + 1}/{MAX_FRAME_ATTEMPTS - 1} ({dest.name}): {issues}")
    assert last is not None
    return last


def _start_parts(beat: dict, style: str, anchor: Optional[Path], product_ref: Optional[str], issues: str) -> list:
    text = (
        "Create ONE vertical 9:16 infographic keyframe for a short-form video ad.\n\n"
        f"{style}\n\n"
        f"BEAT CONCEPT: {beat['concept']}\nLAYOUT TYPE: {beat.get('layout', 'device_ui')}\n"
        f"EXACT FRAME CONTENT: {beat['start_state']}\n"
        f"ON-SCREEN TEXT - render exactly these strings, spelled exactly, and no other text anywhere: {json.dumps(beat['labels'])}\n\n"
        "Make it detailed and information-rich: clear hierarchy, supporting icons or UI elements that make the idea obvious without audio. "
        "Crisp vector edges, large readable type, nothing cropped."
    )
    if anchor is not None:
        text += "\n\nA style reference image is attached. Match its background, typography, icon style, palette and spacing exactly, but draw the new illustration described above."
    if product_ref and beat.get("show_product"):
        text += "\nA product reference photo is attached. The product shown must match it exactly in shape, colors and packaging."
    if issues:
        text += f"\n\nFIX THESE PROBLEMS FROM THE PREVIOUS ATTEMPT: {issues}"
    parts: list = [{"type": "text", "text": text}]
    if anchor is not None:
        parts.append({"type": "image_url", "image_url": {"url": _to_data_url(anchor, 1280)}})
    if product_ref and beat.get("show_product"):
        parts.append({"type": "image_url", "image_url": {"url": product_ref}})
    return parts


def _end_parts(beat: dict, start_img: Path, issues: str) -> list:
    text = (
        "Edit this exact image. Keep IDENTICAL: background, layout, camera, element positions, sizes, colors, typography and all text labels "
        f"({json.dumps(beat['labels'])}, same spelling). Change ONLY this: {beat['end_state']}. "
        "ALL text and numbers stay exactly as they are, character for character. Nothing else changes. Render text exactly and crisply."
    )
    if issues:
        text += f"\nFIX THESE PROBLEMS FROM THE PREVIOUS ATTEMPT: {issues}"
    return [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": _to_data_url(start_img)}},
    ]


async def _product_ref_data_url(ref_url: str) -> Optional[str]:
    if not ref_url:
        return None
    if ref_url.startswith("data:image/"):
        return ref_url
    local = UPLOAD_DIR / ref_url.split("/")[-1].split("?")[0]
    try:
        if local.exists():
            return _to_data_url(local, 1280)
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(ref_url)
            r.raise_for_status()
        tmp = UPLOAD_DIR / "_ref_tmp.img"
        tmp.write_bytes(r.content)
        out = _to_data_url(tmp, 1280)
        tmp.unlink(missing_ok=True)
        return out
    except Exception:
        return None


# ─── Image → video per beat ──────────────────────────────────────────────────

def _still_clip(image: Path, duration: float, out: Path) -> None:
    frames = int(duration * 30) + 1
    vf = (
        f"scale=1080:1920,zoompan=z='min(zoom+0.0004,1.06)':d={frames}:s=1080x1920:fps=30,format=yuv420p"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", str(image), "-vf", vf, "-t", f"{duration:.3f}",
         "-c:v", "libx264", "-crf", "18", str(out)],
        capture_output=True, text=True, check=True,
    )


def _motion_prompt(beat: dict) -> str:
    return (
        f"Animate this infographic from the first frame to the last frame: {beat.get('motion', beat['end_state'])} "
        f"Final state: {beat['end_state']} "
        "Locked static camera, no zoom, no pan. All text labels stay perfectly sharp, readable, unchanged in spelling and position. "
        "Flat vector infographic animation, crisp edges, clean motion, no film grain, no extra objects, no people, no watermark. Vertical 9:16."
    )


async def _render_beat_clip(
    job_id: str,
    scene_idx: int,
    beat_idx: int,
    beat: dict,
    start_img: Path,
    end_img: Path,
    sem: asyncio.Semaphore,
    log: LogFn,
    video_model: str = "",
    video_provider: str = "local",
    local_video_model: str = "ltx23_distilled_q6",
) -> Path:
    out = UPLOAD_DIR / f"infog_clip_{job_id}_{scene_idx}_{beat_idx}.mp4"
    async with sem:
        try:
            start_url = f"{SERVER_URL}/uploads/{start_img.name}"
            end_url = f"{SERVER_URL}/uploads/{end_img.name}"
            raw_url = await generate_kling_broll(
                prompt=_motion_prompt(beat),
                target_duration_sec=beat["duration"],
                segment_label=f"scene{scene_idx + 1}-beat{beat_idx + 1}",
                first_frame_url=start_url,
                last_frame_url=end_url,
                model=video_model or VIDEO_MODEL,
                resolution=VIDEO_RESOLUTION,
                infographic=True,
                on_log=log,
                video_provider=video_provider,
                local_video_model=local_video_model,
            )
            local = UPLOAD_DIR / raw_url.split("/")[-1].split("?")[0]
            if not local.exists():
                async with httpx.AsyncClient(timeout=180) as client:
                    r = await client.get(raw_url)
                    r.raise_for_status()
                    local.write_bytes(r.content)
            return local
        except Exception as exc:
            log(f"⚠️ Video generation failed for scene {scene_idx + 1} beat {beat_idx + 1} ({exc}); using animated still.")
            await asyncio.get_event_loop().run_in_executor(None, _still_clip, end_img, beat["duration"], out)
            return out


# ─── Orchestrator ────────────────────────────────────────────────────────────

async def build_infographic_scenes(
    job_id: str,
    segments: List[dict],
    analysis: dict,
    product_name: str,
    mode: str,
    product_image_url: str,
    on_log: Optional[LogFn] = None,
    image_model: str = "",
    video_model: str = "",
    video_provider: str = "local",
    local_video_model: str = "ltx23_distilled_q6",
    image_provider: str = "local",
    local_image_model: str = "flux-dev",
) -> Dict[int, str]:
    """Return {segment_index: server URL of the finished, voice-muxed scene clip} for every B-roll scene that succeeded."""
    log: LogFn = on_log or (lambda m: None)
    UPLOAD_DIR.mkdir(exist_ok=True)
    idxs = [i for i, s in enumerate(segments) if s.get("scene_type") == "b_roll"]

    if not idxs:
        return {}

    style = build_style_bible(analysis, product_name)
    product_ref = await _product_ref_data_url(product_image_url) if mode == "physical" else None

    # 1. Storyboards (parallel)
    async def _sb(i: int):
        seg = segments[i]
        wav = UPLOAD_DIR / f"audio_{job_id}_{i}.wav"
        dur = float(seg.get("audio_duration_sec") or get_media_duration(wav))
        hint = (seg.get("scene_direction") or {}).get("kling_prompt_start") or seg.get("kling_prompt") or ""
        beats = await build_storyboard(seg["text"], dur, analysis, product_name, mode, hint, wav)
        log(f"🧩 Scene {i + 1}: {len(beats)} infographic beats - " + " | ".join(b["concept"][:50] for b in beats))
        return i, beats

    sb_results = await asyncio.gather(*[_sb(i) for i in idxs], return_exceptions=True)
    storyboards: Dict[int, List[dict]] = {}
    for r in sb_results:
        if isinstance(r, Exception):
            log(f"⚠️ Storyboard failed for one scene: {r}")
        else:
            storyboards[r[0]] = r[1]
    if not storyboards:
        return {}

    # 2. Keyframes: one style anchor first, then all remaining start frames in parallel, then end frames as edits
    img_sem = asyncio.Semaphore(IMAGE_CONCURRENCY)
    order = sorted(storyboards)
    first_i = order[0]
    starts: Dict[tuple, Path] = {}
    ends: Dict[tuple, Path] = {}

    async def _start(i: int, b: int, anchor: Optional[Path]):
        beat = storyboards[i][b]
        dest = UPLOAD_DIR / f"infog_{job_id}_{i}_{b}_start.jpg"
        async with img_sem:
            log(f"🖼️ Scene {i + 1} beat {b + 1}: rendering start frame ({beat['concept'][:50]})")
            starts[(i, b)] = await _make_frame(
                dest, lambda iss: _start_parts(beat, style, anchor, product_ref, iss),
                beat["labels"], beat["concept"], log, image_model,
                image_provider=image_provider, local_image_model=local_image_model)

    await _start(first_i, 0, None)
    anchor = starts[(first_i, 0)]
    rest = [(i, b) for i in order for b in range(len(storyboards[i])) if (i, b) != (first_i, 0)]
    await asyncio.gather(*[_start(i, b, anchor) for i, b in rest])

    async def _end(i: int, b: int):
        beat = storyboards[i][b]
        dest = UPLOAD_DIR / f"infog_{job_id}_{i}_{b}_end.jpg"
        async with img_sem:
            log(f"🖼️ Scene {i + 1} beat {b + 1}: rendering end frame (state change)")
            ends[(i, b)] = await _make_frame(
                dest, lambda iss: _end_parts(beat, starts[(i, b)], iss),
                beat["labels"], beat["concept"] + " (end state: " + beat["end_state"] + ")", log, image_model,
                image_provider=image_provider, local_image_model=local_image_model)

    await asyncio.gather(*[_end(i, b) for i in order for b in range(len(storyboards[i]))])

    # 3. Veo per beat (parallel)
    vid_sem = asyncio.Semaphore(VIDEO_CONCURRENCY)
    clip_tasks = {
        (i, b): asyncio.create_task(
            _render_beat_clip(
                job_id, i, b, storyboards[i][b], starts[(i, b)], ends[(i, b)], vid_sem, log,
                video_model, video_provider, local_video_model
            )
        )
        for i in order for b in range(len(storyboards[i]))
    }
    await asyncio.gather(*clip_tasks.values())


    # 4. Assemble per scene with the scene's voiceover
    results: Dict[int, str] = {}
    for i in order:
        try:
            wav = UPLOAD_DIR / f"audio_{job_id}_{i}.wav"
            out = UPLOAD_DIR / f"broll_muxed_{job_id}_{i}.mp4"
            total = float(segments[i].get("audio_duration_sec") or get_media_duration(wav))
            clips = [(clip_tasks[(i, b)].result(), storyboards[i][b]["duration"]) for b in range(len(storyboards[i]))]
            await asyncio.get_event_loop().run_in_executor(None, compose_beat_scene, clips, wav, out, total)
            results[i] = f"{SERVER_URL}/uploads/{out.name}"
            log(f"✅ Scene {i + 1} infographic B-roll assembled ({total:.1f}s, {len(clips)} beats)")
        except Exception as exc:
            log(f"⚠️ Assembly failed for scene {i + 1}: {exc}")
    return results
