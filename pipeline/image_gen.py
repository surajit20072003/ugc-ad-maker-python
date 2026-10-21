"""
pipeline/image_gen.py
──────────────────────
Generate UGC avatar images and cinematic B-roll keyframes via OpenRouter image models.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE    = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_IMG_URL = "https://openrouter.ai/api/v1/images"
CHAT_MODEL         = "anthropic/claude-sonnet-5"

# Default image model — Google Nano Banana Pro (Gemini 3 Pro Image) for highest commercial quality
IMAGE_MODEL = os.getenv("UGC_IMAGE_MODEL", "google/gemini-3-pro-image")
FALLBACK_IMAGE_MODEL = "google/gemini-3.1-flash-image"

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

    pose_map = {
        "hook": (
            "relaxed natural posture facing the camera, very slight lean in; calm, softly engaged expression with eyes looking steadily into the lens "
            "and the mouth gently closed or only barely parted; one hand resting naturally near the chest or lightly holding the product, "
            "no pointing, no big gestures"
        ),
        "body": (
            "relaxed storytelling posture: product held naturally and still at chest level in one hand, "
            "the other hand resting down or lightly open, calm steady eye contact with the camera, faint natural smile at most"
        ),
        "cta": (
            "relaxed sincere posture, soft natural closed-mouth smile (no teeth), calm eye contact with the lens, "
            "one hand resting naturally or lightly holding the product, no thumbs-up pose, no exaggerated gesture"
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
            "- Ultra-realistic photography, authentic UGC creator feel (Fujifilm 35mm f/2.0 look)\n"
            "- REALISM: natural skin with visible pores and slight asymmetry, no airbrushing or beauty filter, subtle neutral-calm expression, "
            "no exaggerated emotion, no wide eyes, no teeth showing, anatomically correct hands with five fingers, real phone-camera look\n"
            "- FRAMING: camera straight and level at eye height on a propped-up phone, face centered and facing the lens, shoulders square, NO tilted frame, NO selfie arm or blurred foreground limb, nothing covering the face"
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
            "- Hyper-realistic, candid social media creator aesthetic\n"
            "- REALISM: natural skin with visible pores and slight asymmetry, no airbrushing or beauty filter, subtle neutral-calm expression, "
            "no exaggerated emotion, no wide eyes, no teeth showing, anatomically correct hands with five fingers, real phone-camera look\n"
            "- FRAMING: camera straight and level at eye height on a propped-up phone, face centered and facing the lens, shoulders square, NO tilted frame, NO selfie arm or blurred foreground limb, nothing covering the face"
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
                    "Expressions must be calm and natural, never exaggerated or posed. "
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


async def generate_broll_keyframe_prompts(
    product_name: str,
    analysis: dict,
    segment: dict,
    mode: str = "physical",
    lighting_anchor: str = "",
    previous_end_prompt: str = "",
) -> dict:
    """
    Generate elite start-frame, end-frame, and Veo motion prompts for keyframe-guided B-roll.
    Supports lighting anchors and previous beat continuity hints.
    """
    colors = ", ".join(
        f"{c.get('name', '')} {c.get('hex', '')}".strip()
        for c in analysis.get("color_scheme", [])
    ) or "premium neutral commercial colors"
    brand = analysis.get("brand_name", product_name)
    product_type = analysis.get("product_type", "product")
    visual_desc = analysis.get("visual_description", "clean premium product")
    audience = analysis.get("audience", "target customers")
    device = analysis.get("device_type", "laptop and smartphone")
    use_case = analysis.get("use_case", "solving the customer's core problem")
    scene_text = segment.get("text", "")
    raw_prompt = segment.get("kling_prompt") or segment.get("scene_prompt") or "product b-roll"
    label = segment.get("label", "b-roll")

    if mode == "software":
        subject_context = (
            f"Software/service: {product_name} by {brand}. Audience: {audience}. Use case: {use_case}. "
            f"Device context: pristine unbranded {device}, laptop, tablet, and smartphone displays. "
            "Show abstract modern UI structure only: clean cards, gradients, charts, and layout blocks; "
            "NO readable words, NO real website text, NO logos, NO fake letters."
        )
    else:
        subject_context = (
            f"Physical product: {product_name} by {brand}. Product type: {product_type}. Visual details: {visual_desc}. "
            "Show premium macro textures, clean packaging silhouette, tactile usage detail, and lifestyle context; "
            "avoid readable label text and avoid fake logos."
        )

    lighting_spec = lighting_anchor or (
        "Softbox key light from upper-left at 45 degrees, warm white 5500K. "
        "Subtle diffused fill light from right. Deep neutral dark background."
    )

    continuity_section = f"\nCONTINUITY FROM PREVIOUS SCENE: {previous_end_prompt}" if previous_end_prompt else ""

    user_msg = f"""
Create professional AI-image and image-to-video prompts for one vertical 9:16 UGC ad B-roll scene.

SCENE LABEL: {label}
SPOKEN VOICEOVER: {scene_text}
RAW DIRECTOR IDEA: {raw_prompt}
BRAND / COLOR SYSTEM: {colors}
SUBJECT CONTEXT: {subject_context}
MANDATORY LIGHTING SETUP: {lighting_spec}{continuity_section}

You must design a premium commercial transition using two exact keyframes:
1. start_prompt: opening frame image prompt (100+ words).
2. end_prompt: ending frame image prompt (100+ words).
3. video_motion_prompt: camera and motion instructions for Google Veo 3.1 Fast to interpolate smoothly from start to end (80+ words).

QUALITY REQUIREMENTS:
- Photorealistic high-end commercial product photography, not AI art.
- Vertical 9:16 composition, premium TikTok/Reels ad look.
- LITERAL VOICEOVER SYNC: If voiceover mentions lag/speed/results, show literal physical evidence on screen (e.g. buffering spinner or instant 100% load bar).
- Clean, pristine, undamaged objects only.
- If showing screens: pristine devices, responsive modern UI, abstract layout blocks only, zero readable text.
- No broken phones, no cracked screens, no damaged hardware, no glitch UI, no fake letters.
- Lighting continuity between start and end: follow MANDATORY LIGHTING SETUP strictly.
- BANNED BUZZWORDS: cinematic, beautiful, dynamic, abstract, stunning, elegant, seamless. Use concrete physical descriptors only.
- The end frame must feel like a natural reveal from the start frame.

Return ONLY valid JSON with exactly these string keys:
{{"start_prompt":"...", "end_prompt":"...", "video_motion_prompt":"..."}}
""".strip()


    payload = {
        "model": CHAT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an elite Hollywood Director of Photography, AI commercial prompt engineer, and product ad cinematographer. "
                    "You create strict photorealistic keyframe prompts for image-to-video models. "
                    "You never include readable text, logos, watermarks, subtitles, broken devices, or fake UI glyphs. "
                    "Return only raw JSON, no markdown fences."
                ),
            },
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.55,
        "max_tokens": 1400,
    }

    async with httpx.AsyncClient(timeout=75) as client:
        resp = await client.post(OPENROUTER_BASE, headers=_chat_headers(), json=payload)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()

    cleaned = raw.replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        data = {}

    start_prompt = data.get("start_prompt") or (
        f"Vertical 9:16 premium commercial keyframe, {subject_context}, macro close-up, pristine materials, "
        f"brand colors {colors}, cinematic softbox lighting, shallow depth of field, no text, no logos, no damaged objects"
    )
    end_prompt = data.get("end_prompt") or (
        f"Vertical 9:16 premium commercial reveal frame, {subject_context}, wider composition, responsive clean layout, "
        f"same lighting and color grade, pristine details, no text, no logos, no damaged objects"
    )
    video_motion_prompt = data.get("video_motion_prompt") or (
        "Smooth cinematic dolly-out and subtle crane-up motion from the first frame to the last frame, realistic parallax, "
        "stable exposure, consistent lighting, premium commercial camera movement, no morphing, no text artifacts"
    )

    shared_quality = (
        " Ultra-realistic 9:16 vertical commercial photography, 4K sharpness, clean pristine objects, "
        "no readable text, no letters, no logos, no watermark, no subtitles, no captions, no broken phones, "
        "no cracked screens, no damaged hardware, no distorted UI, no fake typography."
    )

    return {
        "start_prompt": f"{start_prompt}{shared_quality}",
        "end_prompt": f"{end_prompt}{shared_quality}",
        "video_motion_prompt": video_motion_prompt,
    }


NEGATIVE_PROMPT = (
    "blurry, watermark, logo, copyright, text cut off, distorted text, "
    "photorealistic faces, stock photo, 16:9 landscape, borders, "
    "low quality, artifacts, noise, ugly"
)


async def generate_ugc_image(
    ugc_prompt: str,
    product_image_url: str = "",
    model: str = "",
    job_id: str = "imggen",
    image_provider: str = "local",
    local_image_model: str = "flux-dev",
) -> str:
    """
    Generate the UGC scene or keyframe image using either Local GPU (Flux) or OpenRouter cloud.
    Returns a publicly accessible server URL.
    """
    upload_dir = Path(__file__).parent.parent / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    server_base = os.getenv("SERVER_URL", "http://localhost:8765").rstrip("/")

    full_prompt = ugc_prompt
    if product_image_url:
        full_prompt = (
            f"{ugc_prompt}, the product matches exactly the appearance and branding "
            f"of the reference product"
        )

    # ── 1. Local GPU Provider (Flux Dev / Schnell / 1.1 Pro) ───────────────────
    if image_provider == "local":
        try:
            from pipeline.local_gpu_client import LocalGPUClient, generate_image_async
            client = LocalGPUClient()
            if client.is_available():
                local_out_path = upload_dir / f"local_img_{job_id}.jpg"
                res_path = await generate_image_async(
                    client=client,
                    prompt=full_prompt,
                    output_path=str(local_out_path),
                    model=local_image_model or "flux-dev",
                    negative_prompt=NEGATIVE_PROMPT,
                )
                if res_path and Path(res_path).exists() and Path(res_path).stat().st_size > 1000:
                    filename = Path(res_path).name
                    return f"{server_base}/uploads/{filename}"
                print(f"[ImageGen] Local GPU generation failed or unsupported, falling back to cloud OpenRouter...")
            else:
                print(f"[ImageGen] Local GPU server not available, falling back to cloud OpenRouter...")
        except Exception as local_err:
            print(f"[ImageGen] Local GPU error ({local_err}), falling back to cloud OpenRouter...")

    # ── 2. Cloud Provider (OpenRouter: GPT-Image-2, Gemini 3 Pro, etc.) ────────
    image_model = model or IMAGE_MODEL

    payload = {
        "model": image_model,
        "prompt": full_prompt,
        "aspect_ratio": "9:16",
    }
    if image_model.startswith("openai/"):
        payload["quality"] = os.getenv("GPT_IMAGE_QUALITY", "medium")

    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(OPENROUTER_IMG_URL, headers=_img_headers(), json=payload)
        if resp.status_code not in (200, 201) and image_model != FALLBACK_IMAGE_MODEL:
            payload["model"] = FALLBACK_IMAGE_MODEL
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

