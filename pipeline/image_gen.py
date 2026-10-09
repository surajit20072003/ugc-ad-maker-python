"""
pipeline/image_gen.py
──────────────────────
Generate a consistent UGC scene image via Claude (prompt) + OpenRouter Image API.

KEY DESIGN PRINCIPLES:
  1. Character Consistency: All 3 segments lock into the same character description,
     attire, hair, and setting from `analysis["character_profile"]`.
  2. Video Animation Readiness: The image MUST be waist-up with BOTH hands visible
     in natural raised/gestural positions at chest/shoulder level.
  3. Real Authentic Aesthetic: Natural room setting, soft window lighting, 9:16
     vertical portrait, smartphone front-camera feel, NO artificial text overlays.
"""
from __future__ import annotations

import base64
import os
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE    = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_IMG_URL = "https://openrouter.ai/api/v1/images"
CHAT_MODEL         = "anthropic/claude-sonnet-5"

# Default image model — gemini works reliably, returns base64, fast and photorealistic
IMAGE_MODEL = os.getenv("UGC_IMAGE_MODEL", "google/gemini-2.5-flash-image")

# 9:16 vertical portrait — compatible with WaveSpeed, OpenRouter video, TikTok/Reels
IMG_WIDTH  = 576
IMG_HEIGHT = 1024


def _chat_headers() -> dict:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8765",
        "X-Title": "UGC Ad Maker",
    }


def _img_headers() -> dict:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8765",
        "X-Title": "UGC Ad Maker",
    }


async def generate_ugc_prompt(
    product_name: str,
    analysis: dict,
    mode: str = "physical",    # "physical" | "software"
    segment: str = "body",     # "hook" | "body" | "cta"
    scene_direction: Optional[dict] = None,
) -> str:
    """
    Craft a photorealistic 9:16 UGC image prompt.
    Anchors to `analysis["character_profile"]` to ensure character consistency across segments.
    """
    char_profile = analysis.get("character_profile", {})
    char_desc    = char_profile.get("description", "relatable 25-28 year old creator")
    char_attire  = char_profile.get("attire", "casual neutral comfortable clothing")
    char_setting = char_profile.get("setting", "cozy sunlit bedroom vanity or desk")

    colors = ", ".join(c.get("name", "") for c in analysis.get("color_scheme", [])) or "natural neutral tones"
    brand  = analysis.get("brand_name", product_name)

    # Pose and energy instructions per segment
    pose_map = {
        "hook": (
            "leaning slightly forward toward camera with wide engaged eyes and candid surprised expression; "
            "one hand raised to shoulder height with index finger gesturing towards viewer or product, "
            "other hand held near chest — authentic freeze-frame of energetic speech"
        ),
        "body": (
            "natural mid-story storytelling posture: one hand visibly holding or touching the product at chest level, "
            "other hand open with relaxed palm gesturing outward to emphasize a point, "
            "warm relatable eye contact with camera"
        ),
        "cta": (
            "approachable friendly smile directly into the lens, "
            "one hand giving a relaxed thumbs-up or gentle open-palm gesture toward the camera, "
            "confident relaxed posture recommending a favorite product to a friend"
        ),
    }
    pose = pose_map.get(segment, pose_map["body"])

    if scene_direction and scene_direction.get("movement_in_scene"):
        pose = f"{pose}. Action nuance: {scene_direction['movement_in_scene']}"

    if mode == "software":
        device = analysis.get("device_type", "laptop")
        user_msg = (
            f"Generate a photorealistic image generation prompt for a 9:16 vertical UGC testimonial photo.\n\n"
            f"LOCKED CHARACTER: {char_desc}\n"
            f"LOCKED ATTIRE: {char_attire}\n"
            f"LOCKED ENVIRONMENT: {char_setting}\n"
            f"PRODUCT: {product_name} (software used on {device} visible in scene)\n"
            f"POSE & EXPRESSION: {pose}\n\n"
            "MANDATORY PHOTOGRAPHY RULES:\n"
            "- WAIST-UP framing — BOTH hands MUST be clearly visible in frame (essential for video lipsync animation)\n"
            "- 9:16 vertical portrait, smartphone selfie or handheld camera angle\n"
            "- Natural window daylight, authentic soft skin texture, fine film grain\n"
            "- NO watermarks, NO text banners, NO UI subtitles rendered on image\n"
            "- Ultra-realistic photography, authentic UGC creator feel (Fujifilm 35mm f/2.0 look)"
        )
    else:
        prod_type   = analysis.get("product_type", "holdable")
        visual_desc = analysis.get("visual_description", "clean product")
        visible_txt = analysis.get("visible_text", "")
        user_msg = (
            f"Generate a photorealistic image generation prompt for a 9:16 vertical UGC product testimonial photo.\n\n"
            f"LOCKED CHARACTER: {char_desc}\n"
            f"LOCKED ATTIRE: {char_attire}\n"
            f"LOCKED ENVIRONMENT: {char_setting}\n"
            f"PRODUCT: {product_name} by {brand} ({prod_type}, {visual_desc}, accents in {colors})\n"
            f"VISIBLE LABEL HINT: {visible_txt}\n"
            f"POSE & EXPRESSION: {pose}\n\n"
            "MANDATORY PHOTOGRAPHY RULES:\n"
            "- WAIST-UP framing — BOTH hands MUST be clearly visible in frame, product held at chest level\n"
            "- 9:16 vertical portrait, authentic smartphone camera selfie feel\n"
            "- Soft natural daylight, warm indoor environment, subtle depth of field\n"
            "- NO AI text gibberish, NO overlay subtitles, NO artificial stickers\n"
            "- Hyper-realistic, candid social media creator aesthetic"
        )

    payload = {
        "model": CHAT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You write image prompts for photorealistic AI diffusion models. "
                    "Your prompts create ultra-realistic 9:16 UGC creator photos with locked character consistency. "
                    "Crucial: Character must be shown WAIST-UP with BOTH HANDS VISIBLE in natural positions. "
                    "Output ONLY the prompt text, no quotes, no labels."
                ),
            },
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.7,
        "max_tokens": 500,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(OPENROUTER_BASE, headers=_chat_headers(), json=payload)
        resp.raise_for_status()
        prompt = resp.json()["choices"][0]["message"]["content"].strip()

    return prompt.replace('"', "").replace("\n", " ")


async def generate_ugc_image(
    ugc_prompt: str,
    product_image_url: str = "",
    model: str = "",
    job_id: str = "imggen",
) -> str:
    """
    Call OpenRouter Image API to generate the UGC scene photo.
    Returns a publicly accessible server URL.
    """
    image_model = model or IMAGE_MODEL

    full_prompt = ugc_prompt
    if product_image_url:
        full_prompt = (
            f"{ugc_prompt}, the product matches exactly the appearance and branding "
            f"of the reference product"
        )

    payload = {
        "model": image_model,
        "prompt": full_prompt,
        "width": IMG_WIDTH,
        "height": IMG_HEIGHT,
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(OPENROUTER_IMG_URL, headers=_img_headers(), json=payload)
        resp.raise_for_status()
        result = resp.json()

    data = result.get("data", [])
    if not data:
        raise RuntimeError(f"OpenRouter image generation returned no data: {result}")

    image_entry = data[0]

    if image_entry.get("url"):
        return image_entry["url"]

    if image_entry.get("b64_json"):
        from pipeline.upload import upload_image_bytes
        img_bytes = base64.b64decode(image_entry["b64_json"])
        return await upload_image_bytes(img_bytes, job_id)

    raise RuntimeError(f"OpenRouter image: unexpected response format: {image_entry}")
