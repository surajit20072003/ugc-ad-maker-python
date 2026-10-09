"""
pipeline/script_gen.py
───────────────────────
Generate an elite UGC ad script in 3 segments ([HOOK], [BODY], [CTA])
accompanied by Hollywood/TikTok Director-level visual scene breakdowns:
- Characters (age, attire, emotion, gestures)
- Scene Background & Lighting
- Camera Movement (handheld, selfie angle, micro-shake)
- Movement in Scene & Product Interaction
- Sound Design & Foley
"""
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-sonnet-5"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8765",
        "X-Title": "UGC Ad Maker Director",
    }


SYSTEM_PROMPT = """You are a world-class viral UGC Video Director and Scriptwriter who produces top-performing TikTok, Reels, and YouTube Shorts video ads.

You write ads in two complementary layers:
1. SPOKEN DIALOGUE: Raw, highly conversational, authentic, relatable creator speech. NOT a corporate spokesperson. NOT polished TV commercial talk. Sounds like a friend sending a voice message or talking directly into their phone front-camera.
2. DIRECTOR SCENE PLAN: Inspired by cinematic video prompts (Veo, Wan, Seedance, Kling). Details the character, natural environment, camera angle/movement, tactile product interaction, and sound design for each segment.

RULES FOR SPOKEN DIALOGUE:
- [HOOK] (6-8s): Stops the scroll instantly. Expresses real frustration, visceral curiosity, or unexpected disbelief. DO NOT mention the product name yet. Pure problem or curiosity hook.
- [BODY] (12-15s): The personal discovery moment. "So I tried...", "Honestly when I first used it...". Natural product mention once or twice. Highlights real specific feelings, textures, results.
- [CTA] (4-5s): Low-pressure, high-trust signoff. "Link is right in my bio", "Seriously check it out for yourself".
- Total spoken runtime: 22-28 seconds (~65-80 words total).
- NO hashtags, NO emojis, NO quotation marks around dialogue.

RULES FOR DIRECTOR SCENE PLAN:
- Characters: Describe the character consistently across segments (same person, age 24-28, hair, attire matching product colors, natural expressions).
- Scene Background: Realistic room (sunlit bedroom vanity, minimalist desk, clean modern kitchen) with natural soft lighting.
- Camera Movement: Smartphone selfie aesthetic, subtle handheld micro-shake, natural tilt or snap-zoom for emphasis.
- Movement in Scene: Specific physical interaction (holding bottle at chest level, pointing to label, showing screen, nodding).
- Sound Design: Foley sound effects matching actions (bottle cap click, soft dropper squeeze, laptop tap, ambient room tone).

EXACT OUTPUT FORMAT:
[HOOK]
<spoken hook text only>

[SCENE_HOOK]
Characters: <character description, posture, emotion>
Scene Background: <location, lighting, props, time of day>
Camera Movement: <handheld, smartphone selfie, subtle shake>
Movement in Scene: <character movement and gestures>
Sound Design: <spoken delivery nuance + ambient foley sounds>

[BODY]
<spoken body text only>

[SCENE_BODY]
Characters: <character description, posture, emotion>
Scene Background: <location, lighting, props, time of day>
Camera Movement: <handheld, smartphone selfie, subtle shake>
Movement in Scene: <character handling product, tactile interaction>
Sound Design: <spoken delivery nuance + ambient foley sounds>

[CTA]
<spoken cta text only>

[SCENE_CTA]
Characters: <character description, posture, emotion>
Scene Background: <location, lighting, props, time of day>
Camera Movement: <handheld, smartphone selfie, subtle shake>
Movement in Scene: <friendly wave, thumbs-up, smiling at camera>
Sound Design: <warm parting dialogue delivery + concluding sound>"""


async def generate_script(
    product_name: str,
    product_benefit: str,
    mode: str = "physical",    # "physical" | "software"
    analysis: dict = None,
) -> str:
    """
    Generate a 3-segment UGC script with director scene breakdowns.
    """
    analysis = analysis or {}
    char_profile = analysis.get("character_profile", {})
    char_desc = char_profile.get("description", "relatable 26-year-old creator")
    char_attire = char_profile.get("attire", "casual neutral everyday clothing")
    char_setting = char_profile.get("setting", "cozy brightly lit home room")
    brand = analysis.get("brand_name", product_name)
    color_scheme = ", ".join(c.get("name", "") for c in analysis.get("color_scheme", [])) or "neutral tones"

    if mode == "software":
        device = analysis.get("device_type", "laptop")
        audience = analysis.get("audience", "busy professionals")
        use_case = analysis.get("use_case", "save hours every week")
        user_prompt = (
            f"Write a viral UGC ad screenplay for the software/app: {product_name}\n"
            f"Target Audience: {audience}\n"
            f"Device used on screen: {device}\n"
            f"What it helps do: {use_case}\n"
            f"Core Benefit: {product_benefit}\n\n"
            f"LOCKED CREATOR PROFILE:\n"
            f"- Creator: {char_desc}\n"
            f"- Attire: {char_attire}\n"
            f"- Setting: {char_setting}\n"
            f"- Brand Aesthetics: {color_scheme}\n\n"
            f"Create the spoken script and director breakdown for [HOOK], [BODY], and [CTA]."
        )
    else:
        prod_type = analysis.get("product_type", "product")
        visual_desc = analysis.get("visual_description", "clean packaging")
        visible_text = analysis.get("visible_text", "")
        user_prompt = (
            f"Write a viral UGC ad screenplay for: {product_name} by {brand}\n"
            f"Product Type: {prod_type}\n"
            f"Visual Details: {visual_desc}\n"
            f"Visible Branding/Text: {visible_text}\n"
            f"Core Benefit: {product_benefit}\n\n"
            f"LOCKED CREATOR PROFILE:\n"
            f"- Creator: {char_desc}\n"
            f"- Attire: {char_attire}\n"
            f"- Setting: {char_setting}\n"
            f"- Color Theme: {color_scheme}\n\n"
            f"Create the spoken script and director breakdown for [HOOK], [BODY], and [CTA]."
        )

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0.85,
        "max_tokens": 1200,
    }

    async with httpx.AsyncClient(timeout=75) as client:
        resp = await client.post(OPENROUTER_BASE, headers=_headers(), json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
