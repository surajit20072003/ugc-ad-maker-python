"""
pipeline/local_gpu_client.py
─────────────────────────────
Local GPU server client for image generation (Flux) and image-to-video (LTX-Video 2.3).

Adapted from ai-document-presentation-v3/render/wan/local_gpu_client.py.
Defaults to 9:16 vertical aspect ratio for UGC ad format.

API Endpoints (Wan2GP server at LOCAL_GPU_URL):
  GET  /health              → Health check (200 = ok, 401 = running but auth required)
  POST /upload              → multipart file upload → {"token": "..."}
  POST /generate            → submit I2V or T2V job → {"job_id": "..."}
  GET  /status/<job_id>     → {"status": "pending|processing|completed|failed"}
  GET  /download/<job_id>   → binary .mp4

Image generation (if server supports /generate-image):
  POST /generate-image      → {"job_id": "..."}
  GET  /status/<job_id>     → {"status": "completed", "result": {"image_url": "..."}}
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

LOCAL_GPU_URL = os.environ.get("LOCAL_GPU_URL", "http://204.12.237.78:9090")
LOCAL_GPU_API_KEY = os.environ.get("LOCAL_GPU_API_KEY", "")

POLL_INTERVAL = 20   # seconds between status polls
MAX_POLL_ATTEMPTS = 180  # 180 * 20s = 60 min max

# LTX-Video: frames per second
LTX_FPS = 25
# Duration clamp: server accepts 5–15s
MIN_DURATION = 5
MAX_DURATION = 15


class LocalGPUClient:
    """Client for local GPU server (Wan2GP / LTX-Video + Flux image)."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or os.getenv("LOCAL_GPU_URL") or LOCAL_GPU_URL).rstrip("/")
        api_key = os.getenv("LOCAL_GPU_API_KEY") or LOCAL_GPU_API_KEY
        self.headers = {"x-api-key": api_key, "X-API-Key": api_key} if api_key else {}

    # ── Health ────────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Quick health check — True if server is reachable (200 or 401)."""
        try:
            resp = requests.get(f"{self.base_url}/health", headers=self.headers, timeout=8)
            if resp.status_code in (200, 401):
                logger.info(f"[LocalGPU] Server available (HTTP {resp.status_code})")
                return True
            logger.warning(f"[LocalGPU] Health check returned {resp.status_code}")
            return False
        except requests.exceptions.RequestException as e:
            logger.warning(f"[LocalGPU] Server unreachable: {e}")
            return False

    # ── File Upload ───────────────────────────────────────────────────────────

    def upload_file(self, file_path: str) -> Optional[str]:
        """
        Upload an image/audio file → returns upload token string.
        POST /upload — multipart form-data with 'file' field.
        """
        try:
            with open(file_path, "rb") as f:
                files = {"file": (Path(file_path).name, f)}
                resp = requests.post(
                    f"{self.base_url}/upload", files=files, headers=self.headers, timeout=60
                )
            if resp.status_code != 200:
                logger.error(f"[LocalGPU] Upload failed: {resp.status_code} — {resp.text[:200]}")
                return None
            data = resp.json()
            token = data.get("token") or data.get("image_token") or data.get("file_token")
            if token:
                logger.info(f"[LocalGPU] File uploaded, token: {str(token)[:20]}...")
                return token
            logger.error(f"[LocalGPU] No token in upload response: {data}")
            return None
        except Exception as e:
            logger.error(f"[LocalGPU] Upload error: {e}")
            return None

    # ── Video Generation (I2V / T2V) ─────────────────────────────────────────

    def generate_video(
        self,
        prompt: str,
        duration: int = 5,
        output_path: Optional[str] = None,
        image_path: Optional[str] = None,
        image_path_end: Optional[str] = None,
        aspect_ratio: str = "9:16",
        model: str = "ltx23_distilled_q6",
    ) -> Optional[str]:
        """
        Generate a video on the local GPU server (synchronous).

        Args:
            prompt: Text prompt for video generation
            duration: Duration in seconds (clamped to 5–15s)
            output_path: Where to save the .mp4
            image_path: Optional start frame for image-to-video
            image_path_end: Optional end frame for smooth start→end transition
            aspect_ratio: "9:16" (default) or "16:9"
            model: LTX model name (e.g. "ltx23_distilled_q6")

        Returns:
            str: Path to saved .mp4 on success, None on failure
        """
        # Skip if already valid file
        if output_path:
            existing = Path(output_path)
            if existing.exists() and existing.stat().st_size > 10_000:
                logger.info(f"[LocalGPU] SKIP: file already exists ({existing.stat().st_size // 1024}KB): {output_path}")
                return output_path

        # Upload start frame
        image_token = None
        if image_path and Path(image_path).exists():
            logger.info(f"[LocalGPU] Uploading start-frame: {image_path}")
            image_token = self.upload_file(image_path)
            if not image_token:
                logger.error("[LocalGPU] Failed to upload start frame — aborting")
                return None

        # Upload end frame (non-fatal)
        image_end_token = None
        if image_path_end and Path(image_path_end).exists():
            logger.info(f"[LocalGPU] Uploading end-frame: {image_path_end}")
            image_end_token = self.upload_file(image_path_end)
            if not image_end_token:
                logger.warning("[LocalGPU] Failed to upload end frame — continuing with start frame only")

        try:
            job_id = self._submit_video_job(prompt, duration, image_token, image_end_token, aspect_ratio, model)
            if not job_id:
                return None
            logger.info(f"[LocalGPU] I2V job submitted: {job_id}")
            if not self._wait_for_completion(job_id):
                return None
            return self._download_video(job_id, output_path)
        except Exception as e:
            logger.error(f"[LocalGPU] generate_video failed: {e}")
            return None

    def _submit_video_job(
        self, prompt: str, duration: int,
        image_token: Optional[str] = None,
        image_end_token: Optional[str] = None,
        aspect_ratio: str = "9:16",
        model: str = "ltx23_distilled_q6",
    ) -> Optional[str]:
        """POST /generate — returns job_id or None."""
        # Clamp to LTX valid range
        dur = max(MIN_DURATION, min(MAX_DURATION, int(round(duration))))
        video_length = dur * LTX_FPS  # frames

        # Deterministic seed from prompt for reproducibility
        seed = int(hashlib.md5(prompt.encode("utf-8")).hexdigest()[:8], 16) % 2_147_483_647

        res_map = {"9:16": "720x1280", "16:9": "1280x720", "1:1": "720x720"}
        resolution = res_map.get(aspect_ratio, "720x1280")

        payload: dict = {
            "prompt": prompt,
            "video_length": video_length,
            "resolution": resolution,
            "model": model,
            "seed": seed,
        }
        if image_token:
            payload["image_start_token"] = image_token
        if image_end_token:
            payload["image_end_token"] = image_end_token

        try:
            resp = requests.post(
                f"{self.base_url}/generate", json=payload, headers=self.headers, timeout=30
            )
            if resp.status_code != 200:
                logger.error(f"[LocalGPU] Submit failed: {resp.status_code} — {resp.text[:200]}")
                return None
            data = resp.json()
            job_id = data.get("job_id")
            if not job_id:
                logger.error(f"[LocalGPU] No job_id in response: {data}")
                return None
            return job_id
        except requests.exceptions.RequestException as e:
            logger.error(f"[LocalGPU] Submit error: {e}")
            return None

    def _wait_for_completion(self, job_id: str) -> bool:
        """Poll GET /status/<job_id> until completed or failed."""
        consecutive_errors = 0
        for attempt in range(MAX_POLL_ATTEMPTS):
            try:
                resp = requests.get(
                    f"{self.base_url}/status/{job_id}", headers=self.headers, timeout=15
                )
                if resp.status_code == 200:
                    consecutive_errors = 0
                    data = resp.json()
                    status = data.get("status", "")
                    if status == "completed":
                        logger.info(f"[LocalGPU] Job {job_id} completed")
                        return True
                    if status == "failed":
                        logger.error(f"[LocalGPU] Job {job_id} failed: {data}")
                        return False
                    logger.debug(f"[LocalGPU] Job {job_id} status: {status} (attempt {attempt + 1})")
                else:
                    consecutive_errors += 1
                    logger.warning(f"[LocalGPU] Status check HTTP {resp.status_code}")
                    if consecutive_errors >= 5:
                        logger.error("[LocalGPU] Too many consecutive errors — aborting")
                        return False
            except Exception as e:
                consecutive_errors += 1
                logger.warning(f"[LocalGPU] Poll error: {e}")
                if consecutive_errors >= 5:
                    return False
            time.sleep(POLL_INTERVAL)
        logger.error(f"[LocalGPU] Job {job_id} timed out after {MAX_POLL_ATTEMPTS * POLL_INTERVAL}s")
        return False

    def _download_video(self, job_id: str, output_path: Optional[str]) -> Optional[str]:
        """GET /download/<job_id> and save to output_path."""
        try:
            resp = requests.get(
                f"{self.base_url}/download/{job_id}", headers=self.headers, timeout=120, stream=True
            )
            if resp.status_code != 200:
                logger.error(f"[LocalGPU] Download failed: {resp.status_code}")
                return None
            dest = output_path or f"/tmp/local_gpu_{job_id}.mp4"
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
            size_kb = Path(dest).stat().st_size // 1024
            logger.info(f"[LocalGPU] Video downloaded: {dest} ({size_kb}KB)")
            return dest
        except Exception as e:
            logger.error(f"[LocalGPU] Download error: {e}")
            return None

    # ── Image Generation ──────────────────────────────────────────────────────

    def _wait_for_completion_image(self, job_id: str, poll_interval: int = 3, max_attempts: int = 120) -> bool:
        """Poll GET /status/<job_id> with rapid interval (3s) for image generation."""
        consecutive_errors = 0
        for attempt in range(max_attempts):
            try:
                resp = requests.get(
                    f"{self.base_url}/status/{job_id}", headers=self.headers, timeout=10
                )
                if resp.status_code == 200:
                    consecutive_errors = 0
                    data = resp.json()
                    status = data.get("status", "")
                    if status == "completed":
                        logger.info(f"[LocalGPU] Image job {job_id} completed")
                        return True
                    if status == "failed":
                        logger.error(f"[LocalGPU] Image job {job_id} failed: {data}")
                        return False
                else:
                    consecutive_errors += 1
                    if consecutive_errors >= 5:
                        return False
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    return False
            time.sleep(poll_interval)
        logger.error(f"[LocalGPU] Image job {job_id} timed out after {max_attempts * poll_interval}s")
        return False

    def generate_image(
        self,
        prompt: str,
        output_path: str,
        aspect_ratio: str = "9:16",
        model: str = "flux_dev",
        negative_prompt: str = "",
    ) -> Optional[str]:
        """
        Generate an image using local Flux model on Wan2GP server.
        POST /generate-image → poll (3s) → download.
        Returns output_path on success, None on failure.
        """
        if Path(output_path).exists() and Path(output_path).stat().st_size > 1000:
            return output_path

        res_map = {"9:16": "576x1024", "16:9": "1024x576", "1:1": "1024x1024"}
        resolution = res_map.get(aspect_ratio, "576x1024")

        norm_model = model.replace("-", "_").lower()
        if norm_model in ("flux", "flux_dev", "flux-dev"):
            norm_model = "flux_dev"

        steps = 28
        if "schnell" in norm_model or "turbo" in norm_model:
            steps = 4

        seed = int(hashlib.md5(prompt.encode("utf-8")).hexdigest()[:8], 16) % 2_147_483_647
        payload: dict = {
            "prompt": prompt,
            "resolution": resolution,
            "model": norm_model,
            "seed": seed,
            "steps": steps,
        }

        try:
            resp = requests.post(
                f"{self.base_url}/generate-image", json=payload, headers=self.headers, timeout=30
            )
            if resp.status_code != 200:
                logger.error(f"[LocalGPU] Image submit failed: {resp.status_code} — {resp.text[:200]}")
                return None
            data = resp.json()
            job_id = data.get("job_id")
            if not job_id:
                if data.get("image_b64") or data.get("b64_json"):
                    import base64
                    b64 = data.get("image_b64") or data.get("b64_json")
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(output_path).write_bytes(base64.b64decode(b64))
                    return output_path
                logger.error(f"[LocalGPU] No job_id in image response: {data}")
                return None

            # Poll for completion with rapid interval
            if not self._wait_for_completion_image(job_id, poll_interval=3, max_attempts=120):
                return None

            # Download image (/download-image/{job_id} or fallback to /download/{job_id})
            resp2 = requests.get(
                f"{self.base_url}/download-image/{job_id}", headers=self.headers, timeout=60
            )
            if resp2.status_code != 200:
                resp2 = requests.get(
                    f"{self.base_url}/download/{job_id}", headers=self.headers, timeout=60
                )
            if resp2.status_code != 200:
                logger.error(f"[LocalGPU] Image download failed: {resp2.status_code}")
                return None
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(resp2.content)
            logger.info(f"[LocalGPU] Image saved: {output_path} ({len(resp2.content) // 1024}KB)")
            return output_path

        except Exception as e:
            logger.error(f"[LocalGPU] generate_image failed: {e}")
            return None


# ── Async wrappers ────────────────────────────────────────────────────────────

async def generate_i2v_async(
    client: LocalGPUClient,
    prompt: str,
    image_path: Optional[str],
    image_path_end: Optional[str],
    duration: float,
    output_path: str,
    model: str = "ltx23_distilled_q6",
) -> Optional[str]:
    """Run LocalGPUClient.generate_video in a thread executor (non-blocking)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: client.generate_video(
            prompt=prompt,
            duration=int(round(duration)),
            output_path=output_path,
            image_path=image_path,
            image_path_end=image_path_end,
            aspect_ratio="9:16",
            model=model,
        )
    )


async def generate_image_async(
    client: LocalGPUClient,
    prompt: str,
    output_path: str,
    model: str = "flux-dev",
    negative_prompt: str = "",
) -> Optional[str]:
    """Run LocalGPUClient.generate_image in a thread executor (non-blocking)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: client.generate_image(
            prompt=prompt,
            output_path=output_path,
            aspect_ratio="9:16",
            model=model,
            negative_prompt=negative_prompt,
        )
    )
