"""
pipeline/tts.py
────────────────
VoxCPM TTS integration.

API (from OpenAPI spec at http://204.12.237.78:7861/openapi.json):

  POST /generate/sync
    body: { text, emotion, reference_audio?, language?, webhook_url? }
    header: X-API-Key
    → returns WAV bytes directly (synchronous, waits for completion)

  POST /generate
    → async, returns { job_id, status, gpu_id, queue_position, message }

  GET /status/{job_id}    → poll status
  GET /download/{job_id}  → download WAV bytes
  GET /emotions           → list supported emotion keys

Supported emotions:
  hook, explain, key_term, encourage, excited,
  quiz_question, quiz_correct, quiz_wrong, neutral
"""
import asyncio
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

VOXCPM_URL = os.getenv("VOXCPM_URL", "http://204.12.237.78:7861").rstrip("/")
VOXCPM_API_KEY = os.getenv("VOXCPM_API_KEY", "spassword")

# Map from UI emotion labels to VoxCPM emotion keys
EMOTION_MAP = {
    "excited": "excited",
    "hook": "hook",
    "encourage": "encourage",
    "explain": "explain",
    "neutral": "neutral",
    "quiz_question": "quiz_question",
    "quiz_correct": "quiz_correct",
    "quiz_wrong": "quiz_wrong",
    "key_term": "key_term",
}


def _headers() -> dict:
    return {"X-API-Key": VOXCPM_API_KEY}


async def generate_voiceover_sync(
    text: str,
    emotion: str = "excited",
    language: str = "english",
    timeout: int = 300,
    reference_audio: str = "",
) -> bytes:
    """
    Call POST /generate/sync — blocks until TTS is done.
    Returns raw WAV bytes.
    
    emotion must be one of: hook, explain, key_term, encourage,
                             excited, quiz_question, quiz_correct, quiz_wrong, neutral
    """
    emotion_key = EMOTION_MAP.get(emotion.lower(), "neutral")

    payload = {
        "text": text,
        "emotion": emotion_key,
        "language": language,
        "webhook_url": "",
    }
    if reference_audio:
        payload["reference_audio"] = reference_audio

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{VOXCPM_URL}/generate/sync",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        return resp.content  # raw WAV bytes


async def generate_voiceover_async(
    text: str,
    emotion: str = "excited",
    language: str = "english",
    poll_interval: int = 3,
    max_wait: int = 300,
    reference_audio: str = "",
) -> bytes:
    """
    Async path: POST /generate → poll /status/{job_id} → GET /download/{job_id}.
    Returns raw WAV bytes. Fallback if sync endpoint times out.
    """
    emotion_key = EMOTION_MAP.get(emotion.lower(), "neutral")

    payload = {
        "text": text,
        "emotion": emotion_key,
        "language": language,
        "webhook_url": "",
    }
    if reference_audio:
        payload["reference_audio"] = reference_audio

    async with httpx.AsyncClient(timeout=60) as client:
        # Submit job
        resp = await client.post(
            f"{VOXCPM_URL}/generate",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        job_id = resp.json()["job_id"]

        # Poll status
        elapsed = 0
        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            status_resp = await client.get(
                f"{VOXCPM_URL}/status/{job_id}",
                headers=_headers(),
            )
            status_resp.raise_for_status()
            status_data = status_resp.json()
            status = status_data.get("status", "")

            if status == "completed":
                # Download the WAV
                dl_resp = await client.get(
                    f"{VOXCPM_URL}/download/{job_id}",
                    headers=_headers(),
                )
                dl_resp.raise_for_status()
                return dl_resp.content

            if status == "failed":
                error = status_data.get("error", "unknown error")
                raise RuntimeError(f"VoxCPM TTS failed: {error}")

            elapsed += poll_interval

    raise TimeoutError(f"VoxCPM TTS timed out after {max_wait}s for job {job_id}")


async def generate_voiceover(
    text: str,
    emotion: str = "excited",
    language: str = "english",
    reference_audio: str = "",
) -> bytes:
    """
    Primary entrypoint — tries sync first (faster), falls back to async polling.
    Returns WAV bytes.
    """
    try:
        return await generate_voiceover_sync(text, emotion, language, timeout=300, reference_audio=reference_audio)
    except (httpx.TimeoutException, httpx.HTTPStatusError):
        return await generate_voiceover_async(text, emotion, language, reference_audio=reference_audio)


async def list_emotions() -> list:
    """Return list of supported VoxCPM emotion keys."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{VOXCPM_URL}/emotions", headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def check_health() -> dict:
    """Check VoxCPM service health + GPU status."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{VOXCPM_URL}/health", headers=_headers())
        resp.raise_for_status()
        return resp.json()
