"""
pipeline/upload.py
───────────────────
Local file serving — no Cloudinary needed.

Files are saved to the ./uploads/ directory and served
directly from the FastAPI server at:
  http://<SERVER_IP>:<PORT>/uploads/<filename>

This gives WaveSpeed / OpenRouter a public URL without
any third-party CDN dependency.
"""
from __future__ import annotations

import os
import time
import aiofiles
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Public base URL of this server (used to build CDN-style URLs)
# Set SERVER_URL in .env if your server IP/domain is different
SERVER_URL = os.getenv("SERVER_URL", "http://204.12.237.78:8765").rstrip("/")

UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


async def upload_audio_wav(wav_bytes: bytes, job_id: str = "") -> str:
    """
    Save WAV bytes locally and return a public HTTP URL.
    No CDN required — served directly by the FastAPI app.
    """
    filename = f"audio_{job_id or int(time.time())}.wav"
    filepath = UPLOAD_DIR / filename

    async with aiofiles.open(filepath, "wb") as f:
        await f.write(wav_bytes)

    return f"{SERVER_URL}/uploads/{filename}"


async def upload_image_bytes(image_bytes: bytes, job_id: str = "") -> str:
    """
    Save image bytes locally and return a public HTTP URL.
    Used when OpenRouter returns base64 image data.
    """
    filename = f"image_{job_id or int(time.time())}.jpg"
    filepath = UPLOAD_DIR / filename

    async with aiofiles.open(filepath, "wb") as f:
        await f.write(image_bytes)

    return f"{SERVER_URL}/uploads/{filename}"
