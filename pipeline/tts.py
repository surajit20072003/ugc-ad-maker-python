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
import base64
import os
import subprocess
import tempfile
from pathlib import Path
import httpx
from dotenv import load_dotenv

load_dotenv()

VOXCPM_URL = os.getenv("VOXCPM_URL", "http://204.12.237.78:7861").rstrip("/")
VOXCPM_API_KEY = os.getenv("VOXCPM_API_KEY", "spassword")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_SPEECH_URL = "https://openrouter.ai/api/v1/audio/speech"

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


async def generate_bytedance_voiceover(
    text: str,
    reference_audio: str = "",
    timeout: int = 120,
) -> bytes:
    """
    Generate speech using ByteDance Seed Audio (bytedance-seed/seed-audio-1-0) via OpenRouter.
    If reference_audio is provided, performs instant zero-shot voice cloning.
    Supports self-anchoring: pass segment-0 output as reference_audio for segments 1..N
    to lock voice identity across the full ad without a user-uploaded reference.
    Converts returned audio to standard 24kHz 16-bit mono WAV bytes.
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not configured in .env for ByteDance voiceover")

    payload = {
        "model": "bytedance-seed/seed-audio-1-0",
        "input": text,
        "response_format": "mp3",
    }

    if reference_audio and os.path.exists(reference_audio):
        audio_bytes = Path(reference_audio).read_bytes()
        # Guard: skip anchor if file is too small to be valid audio (e.g. write failure)
        if len(audio_bytes) >= 1000:
            b64 = base64.b64encode(audio_bytes).decode("utf-8")
            payload["input_references"] = [
                {
                    "type": "input_audio",
                    "input_audio": {"data": f"data:audio/wav;base64,{b64}"}
                }
            ]


    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8765",
        "X-Title": "UGC Ad Maker ByteDance TTS",
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(OPENROUTER_SPEECH_URL, headers=headers, json=payload)
        resp.raise_for_status()
        mp3_bytes = resp.content

    # Convert MP3 to standard 24kHz 16-bit mono WAV using seekable temp file
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as in_f, \
         tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as out_f:
        in_path = Path(in_f.name)
        out_path = Path(out_f.name)
        try:
            in_path.write_bytes(mp3_bytes)
            cmd = [
                "ffmpeg", "-y",
                "-i", str(in_path),
                "-acodec", "pcm_s16le",
                "-ar", "24000",
                "-ac", "1",
                str(out_path)
            ]
            subprocess.run(cmd, capture_output=True, check=True)
            return out_path.read_bytes()
        finally:
            if in_path.exists(): in_path.unlink()
            if out_path.exists(): out_path.unlink()


async def generate_voiceover(
    text: str,
    emotion: str = "excited",
    language: str = "english",
    reference_audio: str = "",
    engine: str = "voxcpm",
) -> bytes:
    """
    Primary entrypoint — dispatches to VoxCPM or ByteDance Seed Audio.
    Returns standard WAV bytes.
    """
    if engine.lower() == "bytedance":
        return await generate_bytedance_voiceover(text=text, reference_audio=reference_audio)
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
