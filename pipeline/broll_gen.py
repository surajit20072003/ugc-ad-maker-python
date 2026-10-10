"""
pipeline/broll_gen.py
─────────────────────
Dedicated Kling AI Video generation engine for pure cinematic B-Roll scenes.
Uses OpenRouter Kling Video API (kwaivgi/kling-video-o1) in 9:16 vertical format.
Engineered with prompt enhancements for realistic physics, camera motion, and cinematic lighting.
"""
from __future__ import annotations

import os
import asyncio
import re
from pathlib import Path
from typing import Optional, Callable
import httpx

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_VIDEOS_URL = "https://openrouter.ai/api/v1/videos"
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8765").rstrip("/")
UPLOAD_DIR = Path("uploads")
KLING_DEFAULT_MODEL = "kwaivgi/kling-video-o1"


def _or_headers() -> dict:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://ugc-ad-maker.local",
        "X-Title": "UGC Ad Maker Kling B-Roll Engine",
        "Content-Type": "application/json",
    }


def optimize_kling_prompt(raw_prompt: str, context: Optional[str] = None) -> str:
    """
    Enhance prompt for Kwai Kling Video model:
    - High physics realism
    - Natural lighting & depth of field
    - Smartphone or cinema camera dynamics
    - Native 9:16 vertical framing cues
    """
    cleaned = (raw_prompt or "").strip()
    if not cleaned and context:
        cleaned = f"Cinematic close-up product b-roll for {context}"

    # Remove any dialogue or speech quotes
    cleaned = re.sub(r'\"[^\"]*\"', '', cleaned)
    cleaned = re.sub(r'^(scene\s*\d+|b_roll|kling_prompt)[:\s-]*', '', cleaned, flags=re.IGNORECASE).strip()

    cues = [
        cleaned,
        "ultra realistic cinematic lighting, shallow depth of field, 35mm lens, smooth subtle camera glide, 4k 60fps aesthetic, vertical 9:16 format, high production value, photorealistic texture",
    ]
    return ". ".join([c for c in cues if c])[:950]


async def generate_kling_broll(
    prompt: str,
    target_duration_sec: float = 5.0,
    segment_label: str = "body",
    image_url: Optional[str] = None,
    model: str = KLING_DEFAULT_MODEL,
    poll_interval: int = 12,
    max_wait: int = 600,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Generate cinematic B-roll clip via Kling on OpenRouter.
    Automatically sets duration to 5s or 10s depending on measured audio length.
    Downloads result to uploads/ and returns local URL.
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not configured in .env")

    # Model-specific supported durations
    model_lower = model.lower()
    if "veo" in model_lower:
        # Veo supports 4, 6, 8s
        req_duration = 8 if target_duration_sec > 6.0 else (6 if target_duration_sec > 4.5 else 4)
    elif "seedance" in model_lower:
        # Seedance supports 5, 10s
        req_duration = 10 if target_duration_sec > 5.5 else 5
    elif "kling" in model_lower:
        # Kling supports 5, 10s
        req_duration = 10 if target_duration_sec > 5.5 else 5
    else:
        req_duration = 8 if target_duration_sec > 6.0 else 5

    cinematic_prompt = optimize_kling_prompt(prompt)

    payload = {
        "model": model,
        "prompt": cinematic_prompt,
        "aspect_ratio": "9:16",
        "duration": req_duration,
    }

    if on_log:
        on_log(f"Submitting {segment_label.upper()} to {model} ({req_duration}s clip, target audio {target_duration_sec:.1f}s)...")

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(OPENROUTER_VIDEOS_URL, headers=_or_headers(), json=payload)
        if resp.status_code not in (200, 202):
            err_text = resp.text
            # If rejected or failed on Kling, auto-try Veo 3.1 Fast
            if model != "google/veo-3.1-fast":
                if on_log:
                    on_log(f"⚠️ {model} submission error ({resp.status_code}). Switching to Google Veo 3.1 Fast...")
                return await generate_kling_broll(
                    prompt=prompt,
                    target_duration_sec=target_duration_sec,
                    segment_label=segment_label,
                    model="google/veo-3.1-fast",
                    poll_interval=poll_interval,
                    max_wait=max_wait,
                    on_log=on_log,
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
                if model != "google/veo-3.1-fast":
                    if on_log:
                        on_log(f"⚠️ {model} error ({err_str}). Switching to Google Veo 3.1 Fast...")
                    return await generate_kling_broll(
                        prompt=prompt,
                        target_duration_sec=target_duration_sec,
                        segment_label=segment_label,
                        model="google/veo-3.1-fast",
                        poll_interval=poll_interval,
                        max_wait=max_wait,
                        on_log=on_log,
                    )
                raise RuntimeError(f"B-roll video generation failed: {err}")

    raise TimeoutError(f"Video generation timed out after {max_wait}s for job {job_id}")
