"""
pipeline/broll_gen.py
─────────────────────
High-Fidelity B-Roll Engine using Image-to-Video with Start & End Keyframes:
Features:
  - Generates smooth cinematic 9:16 vertical video interpolating between
    a Start Frame (first_frame) and End Frame (last_frame).
  - Primary video model: Google Veo 3.1 Fast (google/veo-3.1-fast)
  - Automatic fallback: ByteDance Seedance 2.5 (bytedance/seedance-2.5) or Kling Video O1
  - Strict zero-text constraints to eliminate distorted text / cracked device artifacts.
"""
from __future__ import annotations

import asyncio
import base64
import os
import re
from pathlib import Path
from typing import Optional, Callable
import httpx
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_VIDEOS_URL = "https://openrouter.ai/api/v1/videos"
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8765").rstrip("/")
UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
KLING_DEFAULT_MODEL = "google/veo-3.1-fast"

FALLBACK_CHAIN = {
    "bytedance/seedance-1-5-pro": "google/veo-3.1-lite",
    "google/veo-3.1-lite": "google/veo-3.1-fast",
    "google/veo-3.1": "google/veo-3.1-fast",
    "google/veo-3.1-fast": "bytedance/seedance-2.5",
    "bytedance/seedance-2.5": "kwaivgi/kling-video-o1",
}


def _next_model(model: str) -> Optional[str]:
    return FALLBACK_CHAIN.get(model.lower(), "kwaivgi/kling-video-o1" if "kling" not in model.lower() else None)


def _or_headers() -> dict:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://ugc-ad-maker.local",
        "X-Title": "UGC Ad Maker B-Roll Engine",
        "Content-Type": "application/json",
    }


async def _image_to_data_url(image_url: str) -> str:
    """Ensure image is passed as a valid base64 data URL for OpenRouter."""
    if not image_url:
        return ""
    if image_url.startswith("data:image/"):
        return image_url
    filename = image_url.split("/")[-1].split("?")[0]
    local_path = UPLOAD_DIR / filename
    if local_path.exists():
        data = local_path.read_bytes()
        from pipeline.upload import sniff_image_mime
        mime = sniff_image_mime(data)
        b64 = base64.b64encode(data).decode("utf-8")
        return f"data:{mime};base64,{b64}"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(image_url)
        r.raise_for_status()
        from pipeline.upload import sniff_image_mime
        mime = sniff_image_mime(r.content)
        b64 = base64.b64encode(r.content).decode("utf-8")
        return f"data:{mime};base64,{b64}"


def optimize_kling_prompt(raw_prompt: str, context: Optional[str] = None, is_i2v: bool = False) -> str:
    """
    Enhance prompt for cinematic video generation:
    - High physics realism
    - Natural lighting & depth of field
    - Smartphone or cinema camera dynamics
    - Native 9:16 vertical framing cues
    - Strict zero-text constraints to eliminate distorted/alien pseudo-text artifacts
    - Respects and preserves pre-enhanced structured prompts (SUBJECT/MECHANISM/CAMERA)
    """
    cleaned = (raw_prompt or "").strip()
    if not cleaned and context:
        cleaned = f"Product b-roll for {context}"

    # Check if prompt is already an enhanced structured prompt (e.g. from prompt_enhancer)
    is_structured = "MECHANISM:" in cleaned or "CAMERA:" in cleaned or "SUBJECT:" in cleaned

    if is_structured:
        # Strip banned buzzwords but keep the structured sections intact
        from pipeline.visual_sync_validator import sanitize_banned_words
        cleaned = sanitize_banned_words(cleaned)
        if "no visible text" not in cleaned.lower():
            cleaned += (
                " No visible text, no readable words, no letters, no labels, no watermark, "
                "no captions. Pristine modern hardware. 4k 60fps vertical 9:16 format."
            )
        return cleaned[:1200]

    # Remove dialogue, quotes, and text-render directives
    cleaned = re.sub(r'\"[^\"]*\"', '', cleaned)
    cleaned = re.sub(r'\'[^\']*\'', '', cleaned)
    cleaned = re.sub(r'^(scene\s*\d+|b_roll|kling_prompt)[:\s-]*', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'\b(with\s+text|showing\s+text|reading|written|labeled|saying|text\s+overlay|subtitles|caption)\b[^\,\.]*', '', cleaned, flags=re.IGNORECASE).strip()

    # Prevent AI video model from rendering broken/cracked devices when script talks about 'poor mobile experience'
    cleaned = re.sub(r'\bpoor\s+mobile\s+experience\b', 'responsive modern mobile website interface', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bbroken|cracked|damaged|shattered\b', 'pristine flawless', cleaned, flags=re.IGNORECASE)

    if is_i2v:
        motion_cues = "Smooth motorized gimbal dolly push-in and crane glide, seamless interpolation from opening to ending composition, fluid parallax, organic micro-movements, stable lighting continuity"
    else:
        motion_cues = "Smooth subtle camera glide, 35mm lens, shallow depth of field, fluid motion"

    cues = [
        cleaned,
        motion_cues,
        "pristine flawless modern device displays, clean unbranded minimalist aesthetic, no broken phones, no cracked screens, no damaged hardware",
        "no visible text, no readable words, no letters, no labels, no watermark, no captions, no subtitles, zero typography artifacts",
        "ultra realistic lighting, softbox illumination, 4k 60fps aesthetic, vertical 9:16 format, high production value, photorealistic texture",
    ]
    return ". ".join([c for c in cues if c])[:950]



async def _resolve_local_image_path(image_url: str, dest_prefix: str = "frame") -> Optional[str]:
    """Resolve an image URL to a local absolute file path for the GPU client."""
    if not image_url:
        return None
    filename = image_url.split("/")[-1].split("?")[0]
    local_path = UPLOAD_DIR / filename
    if local_path.exists() and local_path.stat().st_size > 100:
        return str(local_path.resolve())
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(image_url)
            r.raise_for_status()
            out_file = UPLOAD_DIR / f"{dest_prefix}_{abs(hash(image_url)) % 100000}.jpg"
            out_file.write_bytes(r.content)
            return str(out_file.resolve())
    except Exception as e:
        print(f"[BrollGen] Could not resolve image path for {image_url}: {e}")
        return None


async def generate_kling_broll(
    prompt: str,
    target_duration_sec: float = 5.0,
    segment_label: str = "body",
    first_frame_url: Optional[str] = None,
    last_frame_url: Optional[str] = None,
    image_url: Optional[str] = None,
    model: str = KLING_DEFAULT_MODEL,
    poll_interval: int = 12,
    max_wait: int = 900,
    on_log: Optional[Callable[[str], None]] = None,
    resolution: Optional[str] = None,
    infographic: bool = False,
    video_provider: str = "local",
    local_video_model: str = "ltx23_distilled_q6",
) -> str:
    """
    Generate cinematic B-roll clip via Local GPU (LTX-Video) or OpenRouter Video API.
    Supports Image-to-Video (I2V) using start and end frame keyframes.
    Downloads result to uploads/ and returns local URL.
    """
    # Determine start and end frame sources
    start_img = first_frame_url or image_url
    end_img = last_frame_url
    is_i2v = bool(start_img)

    # ── 1. Local GPU Provider (LTX-Video 2.3 Distilled) ────────────────────────
    if video_provider == "local":
        try:
            from pipeline.local_gpu_client import LocalGPUClient, generate_i2v_async
            client = LocalGPUClient()
            if client.is_available() and is_i2v:
                if on_log:
                    on_log(f"Submitting {segment_label.upper()} to Local GPU ({local_video_model}, target {target_duration_sec:.1f}s)...")
                start_local_path = await _resolve_local_image_path(start_img, "start")
                end_local_path = await _resolve_local_image_path(end_img, "end") if end_img else None

                broll_id = f"local_broll_{segment_label}_{int(asyncio.get_event_loop().time() * 1000) % 1000000}"
                out_path = str(UPLOAD_DIR / f"{broll_id}.mp4")

                # Camera lock & smooth motion prefix
                enhanced_prompt = (
                    f"Locked static camera. Smooth fluid motion, physically accurate, premium advertising quality. "
                    f"{prompt}"
                )

                res_path = await generate_i2v_async(
                    client=client,
                    prompt=enhanced_prompt,
                    image_path=start_local_path,
                    image_path_end=end_local_path,
                    duration=target_duration_sec,
                    output_path=out_path,
                    model=local_video_model or "ltx23_distilled_q6",
                )
                if res_path and Path(res_path).exists() and Path(res_path).stat().st_size > 10000:
                    filename = Path(res_path).name
                    if on_log:
                        on_log(f"B-Roll [{segment_label.upper()}]: Render completed on Local GPU! ({Path(res_path).stat().st_size // 1024} KB)")
                    return f"{SERVER_URL}/uploads/{filename}"
                else:
                    if on_log:
                        on_log(f"⚠️ Local GPU generation returned no file; falling back to Cloud {model}...")
            else:
                if on_log:
                    on_log(f"⚠️ Local GPU unavailable or no start frame; using Cloud {model}...")
        except Exception as local_err:
            if on_log:
                on_log(f"⚠️ Local GPU error ({local_err}); falling back to Cloud {model}...")

    # ── 2. Cloud Video Provider (OpenRouter: Veo 3.1 / Seedance / Kling) ───────
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not configured in .env and Local GPU generation could not complete.")

    # Model-specific supported durations
    model_lower = model.lower()
    if "veo" in model_lower:
        req_duration = 8 if target_duration_sec > 6.0 else (6 if target_duration_sec > 4.0 else 4)
    elif "seedance" in model_lower:
        req_duration = max(4, min(15, round(target_duration_sec)))
    elif "kling" in model_lower:
        req_duration = 10 if target_duration_sec > 5.5 else 5
    else:
        req_duration = 8 if target_duration_sec > 6.0 else 5


    cinematic_prompt = prompt[:1500] if infographic else optimize_kling_prompt(prompt, is_i2v=is_i2v)

    payload = {
        "model": model,
        "prompt": cinematic_prompt,
        "aspect_ratio": "9:16",
        "duration": req_duration,
        "generate_audio": False,
    }
    if resolution and ("veo" in model_lower or "seedance" in model_lower):
        payload["resolution"] = resolution

    # Add frame_images for Image-to-Video if provided
    if start_img:
        frame_images = []
        first_data = await _image_to_data_url(start_img)
        frame_images.append({
            "type": "image_url",
            "image_url": {"url": first_data},
            "frame_type": "first_frame",
        })
        if end_img:
            last_data = await _image_to_data_url(end_img)
            frame_images.append({
                "type": "image_url",
                "image_url": {"url": last_data},
                "frame_type": "last_frame",
            })
        payload["frame_images"] = frame_images

    mode_label = "I2V Keyframes" if (start_img and end_img) else ("I2V Single Frame" if start_img else "T2V")
    if on_log:
        on_log(f"Submitting {segment_label.upper()} ({mode_label}) to {model} ({req_duration}s clip, target audio {target_duration_sec:.1f}s)...")

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(OPENROUTER_VIDEOS_URL, headers=_or_headers(), json=payload)
        if resp.status_code not in (200, 202):
            err_text = resp.text
            # Automatic fallback progression: Veo -> Seedance -> Kling
            fallback_model = _next_model(model)
            if fallback_model:
                if on_log:
                    on_log(f"⚠️ {model} error ({resp.status_code}: {err_text[:160]}). Falling back to {fallback_model}...")
                return await generate_kling_broll(
                    prompt=prompt,
                    target_duration_sec=target_duration_sec,
                    segment_label=segment_label,
                    first_frame_url=first_frame_url,
                    last_frame_url=last_frame_url,
                    image_url=image_url,
                    model=fallback_model,
                    poll_interval=poll_interval,
                    max_wait=max_wait,
                    on_log=on_log,
                    resolution=resolution,
                    infographic=infographic,
                )
            raise RuntimeError(f"Video submission failed ({resp.status_code}): {err_text}")

        res_data = resp.json()
        job_id = res_data.get("id")
        polling_url = res_data.get("polling_url") or f"{OPENROUTER_VIDEOS_URL}/{job_id}"

        if on_log:
            on_log(f"Video job queued ({job_id}). Polling render...")

        elapsed = 0
        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            poll_resp = await client.get(polling_url, headers=_or_headers())
            if poll_resp.status_code != 200:
                continue

            status_obj = poll_resp.json()
            status = status_obj.get("status")

            if on_log and elapsed % 12 == 0:
                on_log(f"B-Roll [{segment_label.upper()}]: status '{status}' ({elapsed}s elapsed)...")

            if status == "completed":
                unsigned_urls = status_obj.get("unsigned_urls", [])
                if not unsigned_urls:
                    raise RuntimeError(f"Video completed but no URL returned: {status_obj}")

                if on_log:
                    on_log(f"B-Roll [{segment_label.upper()}]: Render completed! Downloading cinematic clip...")

                video_source_url = unsigned_urls[0]
                local_filename = f"broll_{job_id}.mp4"
                local_path = UPLOAD_DIR / local_filename

                dl_resp = await client.get(video_source_url, headers=_or_headers())
                dl_resp.raise_for_status()
                local_path.write_bytes(dl_resp.content)

                if on_log:
                    on_log(f"B-Roll [{segment_label.upper()}]: Saved locally ({len(dl_resp.content) // 1024} KB).")

                return f"{SERVER_URL}/uploads/{local_filename}"

            elif status == "failed":
                err = status_obj.get("error", "Generation error")
                err_str = str(err)
                fallback_model = _next_model(model)
                if fallback_model:
                    if on_log:
                        on_log(f"⚠️ {model} failed ({err_str}). Falling back to {fallback_model}...")
                    return await generate_kling_broll(
                        prompt=prompt,
                        target_duration_sec=target_duration_sec,
                        segment_label=segment_label,
                        first_frame_url=first_frame_url,
                        last_frame_url=last_frame_url,
                        image_url=image_url,
                        model=fallback_model,
                        poll_interval=poll_interval,
                        max_wait=max_wait,
                        on_log=on_log,
                        resolution=resolution,
                        infographic=infographic,
                    )
                raise RuntimeError(f"B-roll video generation failed: {err}")

    raise TimeoutError(f"Video generation timed out after {max_wait}s for job {job_id}")
