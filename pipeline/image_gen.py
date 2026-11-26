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
            "Relaxed natural seated posture, torso angled 5-10 degrees toward camera for intimacy. "
            "Calm direct eye contact with the lens, subtle slight lean-in as if starting a sentence. "
            "One hand resting lightly on the knee or lap, the other near the collarbone in a natural "
            "'let me tell you' gesture. Mouth barely parted or softly closed. "
            "No exaggerated expression — a neutral-to-engaged calm face, like someone who just "
            "discovered something worth sharing. Head perfectly level, no tilt."
        ),
        "body": (
            "Relaxed mid-conversation posture: torso square, both hands visible at chest level. "
            "Product held naturally and still in the primary hand at chest level — fingers relaxed, "
            "not gripping tightly. Free hand open or lightly resting at waist. "
            "Calm steady eye contact with the camera, mouth naturally parted as if mid-sentence. "
            "A faint natural expression of gentle confidence — not smiling, not frowning. "
            "Body language: open and approachable. No stiffness in shoulders or arms."
        ),
        "cta": (
            "Sincere, warm seated posture, slight lean toward camera, shoulders relaxed and open. "
            "Soft natural closed-mouth smile — not forced, corners of mouth gently upturned. "
            "Calm warm eye contact with the lens — the expression of someone genuinely recommending "
            "something they believe in. One hand resting naturally on knee, the other lightly touching "
            "the product or open in a gentle gesture at waist height. No thumbs-up. No teeth showing."
        ),
    }
    pose = pose_map.get(segment, pose_map["body"])

    if scene_direction and scene_direction.get("movement_in_scene"):
        pose = f"{pose}. Scene nuance: {scene_direction['movement_in_scene']}"

    if mode == "software":
        device = analysis.get("device_type", "laptop")
        user_msg = (
            f"Write a highly detailed, technically precise image generation prompt for an AI diffusion model.\n\n"
            f"=== LOCKED CHARACTER PROFILE ===\n"
            f"Person: {char_desc}\n"
            f"Attire: {char_attire}\n"
            f"Environment: {char_setting}\n"
            f"Product: {product_name} (software shown on {device} in the scene)\n"
            f"Pose & Expression: {pose}\n\n"
            f"=== SCENE REQUIREMENTS ===\n"
            "- FORMAT: 9:16 vertical portrait (576x1024px), smartphone selfie or propped-phone angle at eye height\n"
            "- FRAMING: Waist-up shot. BOTH hands clearly in frame. Face centered and facing lens. Shoulders square to camera.\n"
            f"- The {device} should be partially visible on a desk/table in the lower frame, showing the product's UI as a blurred background detail.\n"
            "- LIGHTING: Soft, natural window daylight from the left side. Subtle warm 5000K room ambient fill. No harsh shadows. No ring light glare.\n"
            "- DEPTH OF FIELD: Shallow DOF — creator's face and hands in sharp focus, background environment (room, desk, bookshelf, plants) pleasantly blurred at f/2.0.\n"
            "- SKIN: Photorealistic natural skin with visible pores, fine texture, slight asymmetry, no airbrushing or smoothing filter.\n"
            "- HAIR: Natural, slightly imperfect hair — a few wisps out of place as if freshly filmed, not styled for a studio shoot.\n"
            "- CAMERA LOOK: Authentic smartphone camera look — slight warm exposure, natural color grade, fine digital noise/grain, no professional studio feel.\n"
            "- BACKGROUND: Real room interior visible through the shallow DOF: bookshelves, a plant, desk clutter, soft curtains, or a TV — any authentic home/office environment that matches the character setting.\n"
            "- FORBIDDEN: NO watermarks, NO text overlays, NO UI subtitles, NO captions rendered into the image. NO stock-photo artificiality. NO beauty filter. NO tilted frame. NO selfie arm or blurred foreground limb. NO hands covering the face.\n"
            "- HANDS: Anatomically correct hands with five fingers each. Must be clearly visible. Natural finger positioning, not splayed or clenched.\n"
            "Output ONLY the prompt text. No quotes, no labels, no preamble."
        )
    else:
        prod_type   = analysis.get("product_type", "holdable")
        visual_desc = analysis.get("visual_description", "clean product")
        visible_txt = analysis.get("visible_text", "")
        user_msg = (
            f"Write a highly detailed, technically precise image generation prompt for an AI diffusion model.\n\n"
            f"=== LOCKED CHARACTER PROFILE ===\n"
            f"Person: {char_desc}\n"
            f"Attire: {char_attire}\n"
            f"Environment: {char_setting}\n"
            f"Product: {product_name} by {brand} — {prod_type}, {visual_desc}. Brand accent colors: {colors}.\n"
            f"Label visible on product: {visible_txt}\n"
            f"Pose & Expression: {pose}\n\n"
            f"=== SCENE REQUIREMENTS ===\n"
            "- FORMAT: 9:16 vertical portrait (576x1024px), authentic smartphone selfie or propped-phone camera at eye level\n"
            "- FRAMING: Waist-up shot. BOTH hands visible. Product held at chest level in the primary hand. Face centered, shoulders square.\n"
            "- PRODUCT HANDLING: Product appears naturally held — the creator holds it the way a real person would, not posed like a catalog shot.\n"
            "- LIGHTING: Warm natural window light from the side. Soft ambient room light. Slight warm color cast. No flash, no harsh shadows.\n"
            "- DEPTH OF FIELD: Shallow DOF (f/2.0 equivalent) — creator's face and hands/product sharp, background environment pleasantly blurred.\n"
            "- BACKGROUND: Real home environment visible softly blurred behind the creator: a vanity mirror, bedside table, shelves with items, warm-toned walls, indoor plants, or similar authentic home details. Must match the character setting.\n"
            "- SKIN: Photorealistic, natural skin texture with visible pores and slight asymmetry. Zero airbrushing, no beauty filter smoothing.\n"
            "- HAIR: Natural, slightly casual — looks like someone filming themselves at home, not a studio model.\n"
            "- CAMERA: Authentic smartphone camera aesthetic: slight warm exposure, natural film-grain texture, no professional studio lighting setup visible.\n"
            "- HANDS: Anatomically correct five-fingered hands. Clearly visible. Relaxed natural grip on product.\n"
            "- FORBIDDEN: NO watermarks, NO text overlays, NO AI-generated text or logos on product labels (can show blurred label shape), NO captions, NO stock-photo stiffness, NO selfie arm, NO beauty filter, NO titled frame.\n"
            "Output ONLY the prompt text. No quotes, no labels, no preamble."
        )

    payload = {
        "model": CHAT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an elite product ad photographer and AI diffusion prompt engineer specializing in "
                    "photorealistic UGC (User Generated Content) creator videos and testimonial photos. "
                    "Your prompts reliably produce ultra-realistic 9:16 smartphone-camera-style photos with "
                    "locked character consistency, natural environment depth, and authentic human expressions. "
                    "Critical rules: WAIST-UP framing with BOTH HANDS VISIBLE. Real room background with DOF. "
                    "Natural skin, no beauty filter. No exaggerated expressions. No AI-obvious artifacts. "
                    "Output ONLY the image prompt text, nothing else."
                ),
            },
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.6,
        "max_tokens": 700,
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

