"""
pipeline/video_gen.py
──────────────────────
Dual-Engine Video Generation for UGC Ads:
  1. WaveSpeed (Talking Avatar & Hand Gestures via InfiniteTalk / LTX-2.3)
  2. OpenRouter Video API (Generative Video: Veo 3.1, Seedance, Kling, Wan, HeyGen)

Both engines output standard 9:16 vertical clips saved to ./uploads/
and served via the local server URL.
"""
from __future__ import annotations

import asyncio
import base64
import math
import os
import re
import time
from pathlib import Path
from typing import Optional, Callable

import httpx
from dotenv import load_dotenv

load_dotenv()

WAVESPEED_API_KEY  = os.getenv("WAVESPEED_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
SERVER_URL         = os.getenv("SERVER_URL", "http://localhost:8765").rstrip("/")
# OpenRouter only accepts HTTPS URLs for audio inputs; set this to a public HTTPS base that serves ./uploads at /uploads
PUBLIC_HTTPS_URL   = os.getenv("PUBLIC_HTTPS_URL", "").rstrip("/")
AVATAR_RESOLUTION  = os.getenv("AVATAR_RESOLUTION", "1080p")
AVATAR_EXPRESSIVENESS = os.getenv("AVATAR_EXPRESSIVENESS", "low")

UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# WaveSpeed endpoints
WAVESPEED_LIPSYNC_URL = "https://api.wavespeed.ai/api/v3/wavespeed-ai/infinitetalk"
WAVESPEED_FAST_URL    = "https://api.wavespeed.ai/api/v3/wavespeed-ai/infinitetalk-fast"
WAVESPEED_LTX_URL     = "https://api.wavespeed.ai/api/v3/wavespeed-ai/ltx-2.3/lipsync"
WAVESPEED_RESULT_URL  = "https://api.wavespeed.ai/api/v3/predictions/{id}/result"

# OpenRouter Video endpoints
OPENROUTER_VIDEOS_URL = "https://openrouter.ai/api/v1/videos"


def _ws_headers() -> dict:
    return {
        "Authorization": f"Bearer {WAVESPEED_API_KEY}",
        "Content-Type": "application/json",
    }


def _or_headers() -> dict:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8765",
        "X-Title": "UGC Ad Maker",
    }


# ─── Per-segment motion prompts (WaveSpeed & AI Video) ─────────────────────────

REALISM_CORE = (
    "Real person filming a casual smartphone video, speaking naturally and directly to camera. "
    "Calm, subtle facial expressions only: soft natural eyebrow movement, normal blinks, small relaxed head nods, "
    "lips moving naturally in sync with the speech. Mostly still upper body and shoulders. "
    "At most one small, relaxed hand movement at chest level. Natural conversational delivery. "
    "NO exaggerated emotion, NO wide eyes, NO big smile, NO pointing, NO head shaking, NO dramatic gestures, "
    "NO fast movement. Stable framing like a propped-up phone. Realistic skin, no beauty filter."
)

SEGMENT_MOTION_PROMPTS = {
    "hook": REALISM_CORE + " Tone: calm and direct, like telling a friend something you just noticed.",
    "body": REALISM_CORE + " If a product is in hand it is held still and naturally at chest level.",
    "cta": REALISM_CORE + " Tone: relaxed and sincere; a slight, gentle smile only where the words fit.",
}

DEFAULT_MOTION_PROMPT = REALISM_CORE


# ─── Image URL to Base64 Data URL helper ─────────────────────────────────────

async def _image_to_data_url(image_url: str) -> str:
    """
    Ensure the image is passed as a data URL (data:image/jpeg;base64,...)
    which OpenRouter accepts reliably without external CDN requirements.
    """
    if image_url.startswith("data:image/"):
        return image_url

    # Check if file exists locally in uploads/
    filename = image_url.split("/")[-1].split("?")[0]
    local_path = UPLOAD_DIR / filename
    if local_path.exists():
        data = local_path.read_bytes()
        from pipeline.upload import sniff_image_mime
        mime = sniff_image_mime(data)
        b64 = base64.b64encode(data).decode("utf-8")
        return f"data:{mime};base64,{b64}"

    # Fetch via HTTP
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(image_url)
        r.raise_for_status()
        from pipeline.upload import sniff_image_mime
        mime = sniff_image_mime(r.content)
        b64 = base64.b64encode(r.content).decode("utf-8")
        return f"data:{mime};base64,{b64}"


# ─── Engine A: OpenRouter Video API ──────────────────────────────────────────

async def generate_video_openrouter(
    image_url: str,
    prompt: str = "",
    script: str = "",
    segment: str = "body",
    model: str = "heygen/heygen-video-1",
    poll_interval: int = 5,
    max_wait: int = 600,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Generate video clip using OpenRouter Video API.
    Supports: heygen/heygen-video-1, google/veo-3.1-fast, kwaivgi/kling-video-o1,
              bytedance/seedance-2.5, alibaba/wan-3.0.
    Downloads the resulting MP4 locally to uploads/ and returns public server URL.
    """
    data_url = await _image_to_data_url(image_url)

    # For HeyGen talking avatar models: prompt is the spoken dialogue!
    if "heygen" in model.lower():
        # Prefer exact spoken script over visual directions
        spoken = (script or prompt).strip()
        # Strip any leaked scene/tag prefixes
        spoken = re.sub(r'^(scene\s*\d+|hook|body|cta)[:\s-]*', '', spoken, flags=re.IGNORECASE).strip()
        spoken = spoken.strip('"\'“')

        # Expression & tone style per segment for natural human UGC feel
        if segment == "hook":
            expression = "calm, direct eye contact with camera, subtle natural expression"
        elif segment == "cta":
            expression = "relaxed, sincere and trustworthy, a slight gentle smile"
        else:
            expression = "natural, relaxed, conversational, subtle micro-expressions"

        # Realistic prompt designed for HeyGen avatar speech synthesis
        calm_style = (
            "A real, ordinary person recording a casual phone video, calm and natural. Relaxed face, subtle expressions, "
            "normal blinks, small head nods, still shoulders, at most one small hand movement. "
            "No exaggerated emotion, no wide eyes, no big smile, no pointing, no dramatic gestures. "
            f"Mood: {expression}. Stable framing, realistic skin. "
        )
        speech_part = f'Speaking directly to camera: "{spoken}"'
        # the spoken line must never be truncated by the 900-char cap, so trim the style text instead
        combined_prompt = calm_style[: max(0, 900 - len(speech_part))] + speech_part

        # Calculate exact duration: human speech pace in UGC is ~2.0 to 2.2 words/sec
        words_count = len(spoken.split())
        needed_duration = int(math.ceil(words_count / 1.9)) + 1
        # HeyGen on OpenRouter supports 5 to 15s clips
        duration = max(5, min(15, needed_duration))

    else:
        # Generative diffusion video models (Veo, Kling, Wan, Seedance) need visual motion prompts
        motion = SEGMENT_MOTION_PROMPTS.get(segment, DEFAULT_MOTION_PROMPT)
        combined_prompt = f"{motion} Scene: {prompt[:200]}" if prompt else motion
        words_count = len((prompt or "").split())

        if "kling" in model.lower():
            duration = 10 if words_count > 12 else 5
        elif "veo" in model.lower():
            duration = 8 if words_count > 12 else 6
        else:
            duration = 8 if words_count > 12 else 6

    payload = {
        "model": model,
        "prompt": combined_prompt[:900],
        "aspect_ratio": "9:16",
        "duration": duration,
        "input_references": [
            {
                "type": "image_url",
                "image_url": {"url": data_url},
            }
        ],
    }

    if on_log:
        on_log(f"Submitting {segment.upper()} to OpenRouter ({model}, {duration}s clip)...")

    plain_payload = payload
    if "heygen" in model.lower():
        # HeyGen's own prompt enhancement exaggerates expressions; keep our calm prompt as written
        payload = {**payload, "provider": {"options": {"heygen": {"parameters": {"prompt_enhancement": False}}}}}

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(OPENROUTER_VIDEOS_URL, headers=_or_headers(), json=payload)
        if resp.status_code == 400 and payload is not plain_payload:
            resp = await client.post(OPENROUTER_VIDEOS_URL, headers=_or_headers(), json=plain_payload)
        if resp.status_code not in (200, 202):
            err_text = resp.text
            if any(k in err_text.lower() for k in ["usage guidelines", "privacyinformation", "real person", "sensitivecontent"]):
                if model != "heygen/heygen-video-1":
                    if on_log:
                        on_log(f"⚠️ {model} rejected photo due to face safety filter. Auto-switching to HeyGen Video 1...")
                    return await generate_video_openrouter(
                        image_url=image_url,
                        prompt=prompt,
                        segment=segment,
                        model="heygen/heygen-video-1",
                        poll_interval=poll_interval,
                        max_wait=max_wait,
                        on_log=on_log,
                    )
            raise RuntimeError(f"OpenRouter video submission failed ({resp.status_code}): {err_text}")

        res_data = resp.json()
        job_id = res_data.get("id")
        polling_url = res_data.get("polling_url") or f"{OPENROUTER_VIDEOS_URL}/{job_id}"

        if on_log:
            on_log(f"Job queued on OpenRouter ({job_id}). Polling render...")

        # Poll for completion
        elapsed = 0
        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            poll_resp = await client.get(polling_url, headers=_or_headers())
            if poll_resp.status_code != 200:
                continue

            status_obj = poll_resp.json()
            status = status_obj.get("status")

            if on_log and elapsed % 10 == 0:
                on_log(f"OpenRouter [{segment.upper()}]: status '{status}' ({elapsed}s elapsed)...")

            if status == "completed":
                unsigned_urls = status_obj.get("unsigned_urls", [])
                if not unsigned_urls:
                    raise RuntimeError(f"OpenRouter video completed but no URL: {status_obj}")

                if on_log:
                    on_log(f"OpenRouter [{segment.upper()}]: Render completed! Downloading clip...")

                video_source_url = unsigned_urls[0]
                local_filename = f"openrouter_clip_{job_id}.mp4"
                local_path = UPLOAD_DIR / local_filename

                # Download video with Authorization header
                dl_resp = await client.get(video_source_url, headers=_or_headers())
                dl_resp.raise_for_status()
                local_path.write_bytes(dl_resp.content)

                if on_log:
                    on_log(f"OpenRouter [{segment.upper()}]: Clip saved locally ({len(dl_resp.content) // 1024} KB).")

                return f"{SERVER_URL}/uploads/{local_filename}"

            elif status == "failed":
                err = status_obj.get("error", "Unknown error")
                err_str = str(err)
                if any(k in err_str.lower() for k in ["usage guidelines", "privacyinformation", "real person", "sensitivecontent"]):
                    if model != "heygen/heygen-video-1":
                        if on_log:
                            on_log(f"⚠️ {model} rejected photo due to face filter. Auto-switching to HeyGen Video 1...")
                        return await generate_video_openrouter(
                            image_url=image_url,
                            prompt=prompt,
                            segment=segment,
                            model="heygen/heygen-video-1",
                            poll_interval=poll_interval,
                            max_wait=max_wait,
                            on_log=on_log,
                        )
                raise RuntimeError(f"OpenRouter video generation failed: {err}")

    raise TimeoutError(f"OpenRouter video generation timed out after {max_wait}s for job {job_id}")


# ─── Engine A2: HeyGem Avatar IV (audio-driven, uses OUR voiceover) ──────────

def _public_https_base() -> str:
    if PUBLIC_HTTPS_URL:
        return PUBLIC_HTTPS_URL
    f = Path(__file__).parent.parent / "public_https_url.txt"
    try:
        return f.read_text().strip().rstrip("/")
    except OSError:
        return ""


def _https_audio_url(audio_url: str) -> str:
    filename = audio_url.split("/")[-1].split("?")[0]
    base = _public_https_base()
    if base:
        return f"{base}/uploads/{filename}"
    if audio_url.startswith("https://"):
        return audio_url
    raise RuntimeError(
        "HeyGen Avatar IV needs an HTTPS link to the voiceover. Set PUBLIC_HTTPS_URL in .env, or put the "
        "public HTTPS base URL in public_https_url.txt (project root)."
    )


async def generate_video_avatar_iv(
    image_url: str,
    audio_url: str,
    segment: str = "body",
    resolution: str = "",
    poll_interval: int = 6,
    max_wait: int = 900,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """HeyGen Avatar IV: animates the avatar photo and lip-syncs it to OUR voiceover WAV (voice stays ours)."""
    https_audio = _https_audio_url(audio_url)
    data_url = await _image_to_data_url(image_url)
    payload = {
        "model": "heygen/avatar-iv",
        "prompt": SEGMENT_MOTION_PROMPTS.get(segment, DEFAULT_MOTION_PROMPT)[:900],
        "aspect_ratio": "9:16",
        "resolution": resolution or AVATAR_RESOLUTION,
        "input_references": [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "audio_url", "audio_url": {"url": https_audio}},
        ],
    }
    if on_log:
        on_log(f"Submitting {segment.upper()} to HeyGen Avatar IV with your voiceover audio...")

    heygen_params = {"motion_prompt": REALISM_CORE[:600]}
    if AVATAR_EXPRESSIVENESS:
        heygen_params["expressiveness"] = AVATAR_EXPRESSIVENESS
    tuned = {**payload, "provider": {"options": {"heygen": {"parameters": heygen_params}}}}

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(OPENROUTER_VIDEOS_URL, headers=_or_headers(), json=tuned)
        if resp.status_code == 400:
            if on_log:
                on_log(f"Avatar IV rejected expressiveness options ({resp.text[:160]}); retrying with defaults.")
            resp = await client.post(OPENROUTER_VIDEOS_URL, headers=_or_headers(), json=payload)
        if resp.status_code not in (200, 202):
            raise RuntimeError(f"Avatar IV submission failed ({resp.status_code}): {resp.text[:400]}")
        res = resp.json()
        job_id = res.get("id")
        polling_url = res.get("polling_url") or f"{OPENROUTER_VIDEOS_URL}/{job_id}"
        elapsed = 0
        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            pr = await client.get(polling_url, headers=_or_headers())
            if pr.status_code != 200:
                continue
            obj = pr.json()
            status = obj.get("status")
            if on_log and elapsed % 30 == 0:
                on_log(f"Avatar IV [{segment.upper()}]: {status} ({elapsed}s)...")
            if status == "completed":
                urls = obj.get("unsigned_urls", [])
                if not urls:
                    raise RuntimeError(f"Avatar IV completed without a URL: {obj}")
                dl = await client.get(urls[0], headers=_or_headers())
                dl.raise_for_status()
                name = f"avatar_iv_{job_id}.mp4"
                (UPLOAD_DIR / name).write_bytes(dl.content)
                if on_log:
                    on_log(f"Avatar IV [{segment.upper()}]: clip saved ({len(dl.content) // 1024} KB).")
                return f"{SERVER_URL}/uploads/{name}"
            if status == "failed":
                raise RuntimeError(f"Avatar IV generation failed: {obj.get('error', 'unknown')}")
    raise TimeoutError(f"Avatar IV timed out after {max_wait}s for job {job_id}")


# ─── Engine B: WaveSpeed Lip-Sync (Talking Avatar) ───────────────────────────

async def _poll_wavespeed_result(
    job_id: str,
    poll_interval: int,
    max_wait: int,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    result_url = WAVESPEED_RESULT_URL.format(id=job_id)
    await asyncio.sleep(15)
    elapsed = 15

    async with httpx.AsyncClient(timeout=30) as client:
        while elapsed < max_wait:
            r = await client.get(result_url, headers=_ws_headers())
            r.raise_for_status()
            data = r.json().get("data", {})
            status = data.get("status", "")

            if on_log and elapsed % 15 == 0:
                on_log(f"WaveSpeed status: {status} ({elapsed}s elapsed)...")

            if status == "completed":
                outputs = data.get("outputs", [])
                if outputs:
                    if on_log:
                        on_log("WaveSpeed render completed successfully!")
                    return outputs[0]
                raise RuntimeError(f"WaveSpeed completed but no output URL: {data}")

            if status == "failed":
                raise RuntimeError(f"WaveSpeed generation failed: {data}")

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

    raise TimeoutError(f"WaveSpeed timed out after {max_wait}s for job {job_id}")


async def generate_video_wavespeed(
    image_url: str,
    audio_url: str,
    segment: str = "body",
    resolution: str = "720p",
    fast_mode: bool = False,
    poll_interval: int = 15,
    max_wait: int = 900,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """Generate lipsync video via WaveSpeed (InfiniteTalk with LTX-2.3 fallback)."""
    motion_prompt = SEGMENT_MOTION_PROMPTS.get(segment, DEFAULT_MOTION_PROMPT)

    if on_log:
        on_log(f"Submitting {segment.upper()} to WaveSpeed lipsync...")

    # Try InfiniteTalk first
    try:
        api_url = WAVESPEED_FAST_URL if fast_mode else WAVESPEED_LIPSYNC_URL
        payload = {
            "image": image_url,
            "audio": audio_url,
            "prompt": motion_prompt,
            "resolution": resolution,
            "seed": -1,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(api_url, headers=_ws_headers(), json=payload)
            resp.raise_for_status()
            job_id = resp.json()["data"]["id"]
            return await _poll_wavespeed_result(job_id, poll_interval, max_wait, on_log=on_log)
    except httpx.HTTPStatusError as e:
        err_text = e.response.text
        if "insufficient credits" in err_text.lower():
            raise RuntimeError("WaveSpeed error: Insufficient credits. Please top up WaveSpeed or select OpenRouter Video in UI.")
        if e.response.status_code != 400:
            raise

    # Fallback: LTX-2.3 lipsync
    ltx_res = resolution if resolution in ("480p", "720p") else "720p"
    ltx_payload = {
        "audio": audio_url,
        "image": image_url,
        "prompt": motion_prompt,
        "resolution": ltx_res,
        "seed": -1,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(WAVESPEED_LTX_URL, headers=_ws_headers(), json=ltx_payload)
        if resp.status_code == 400 and "insufficient credits" in resp.text.lower():
            raise RuntimeError("WaveSpeed error: Insufficient credits. Please top up WaveSpeed or switch to OpenRouter Video.")
        resp.raise_for_status()
        job_id = resp.json()["data"]["id"]
        return await _poll_wavespeed_result(job_id, poll_interval, max_wait, on_log=on_log)


# ─── Unified Dispatcher ───────────────────────────────────────────────────────

async def generate_video(
    image_url: str,
    audio_url: str,
    script: str = "",
    segment: str = "body",
    resolution: str = "720p",
    fast_mode: bool = False,
    backend: str = "openrouter",           # "wavespeed" | "openrouter"
    openrouter_model: str = "heygen/heygen-video-1",
    scene_prompt: str = "",
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Unified entrypoint for video clip generation.
    Supports both WaveSpeed lip-sync and OpenRouter AI video engines.
    """
    if backend == "openrouter" and openrouter_model.lower().startswith("heygen/") and audio_url:
        try:
            return await generate_video_avatar_iv(
                image_url=image_url, audio_url=audio_url, segment=segment, on_log=on_log,
            )
        except Exception as e:
            if on_log:
                on_log(f"⚠️ VOICE WARNING: Avatar IV with your voiceover failed ({e}). "
                       "Falling back to HeyGen Video 1, whose own voice will NOT match your cloned voice.")
        if openrouter_model.lower() == "heygen/avatar-iv":
            openrouter_model = "heygen/heygen-video-1"

    if backend == "openrouter":
        return await generate_video_openrouter(
            image_url=image_url,
            prompt=scene_prompt or script,
            script=script,
            segment=segment,
            model=openrouter_model,
            on_log=on_log,
        )

    # WaveSpeed backend requested
    try:
        return await generate_video_wavespeed(
            image_url=image_url,
            audio_url=audio_url,
            segment=segment,
            resolution=resolution,
            fast_mode=fast_mode,
            on_log=on_log,
        )
    except Exception as e:
        # If WaveSpeed fails or runs out of credits, fallback to OpenRouter
        if OPENROUTER_API_KEY:
            if on_log:
                on_log(f"⚠️ WaveSpeed failed ({e}). Auto-falling back to OpenRouter Video ({openrouter_model})...")
            return await generate_video_openrouter(
                image_url=image_url,
                prompt=scene_prompt or script,
                script=script,
                segment=segment,
                model=openrouter_model,
                on_log=on_log,
            )
        raise
