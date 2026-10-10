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


SYSTEM_PROMPT = """You are a world-class viral UGC Video Director and Scriptwriter who produces top-performing TikTok, Reels, and YouTube Shorts cinematic hybrid video ads.

You design ads as a CINEMATIC HYBRID: alternating between an authentic creator talking head ([avatar]) and high-end cinematic product B-Roll ([b_roll]).

KEY ARCHITECTURAL RULES:
1. SPOKEN DIALOGUE:
- Raw, highly conversational, relatable creator speech. NOT a corporate TV commercial. Sounds like a friend sending a voice message or talking directly to their phone camera.
- [HOOK] (5-7s): Stops the scroll instantly. Expresses real frustration, visceral curiosity, or disbelief. DO NOT mention the product name yet. Pure problem hook.
- [BODY] (10-14s): The discovery & demonstration moment. Natural product mention. Highlights real specific textures, feelings, and concrete results.
- [CTA] (4-5s): Low-pressure, high-trust recommendation. "Link is in my bio", "Tap the link below before it sells out".
- Total runtime: ~20-25 seconds (~55-70 words total).
- Naturally include high-impact trigger words where fitting (e.g. website, app, tool, cheap, save, fast, results, free, easy) so graphic badges can emphasize them.
- NO hashtags, NO emojis, NO quotation marks around dialogue.

2. DYNAMIC VISUAL TYPE SELECTION:
- [HOOK]: Visual Type: avatar (creator directly hooks viewer with immediate eye contact).
- [BODY]: Visual Type: b_roll (pure full-screen cinematic B-roll showing product texture, screen action, or aesthetic lifestyle footage while the creator's voiceover plays over it).
- [CTA]: Visual Type: avatar (creator delivers warm personal recommendation with thumbs-up or point down).

3. KLING B-ROLL PROMPTS:
- For [b_roll] segments, provide a dedicated "Kling Prompt" engineered for Kwai Kling Video.
- Focus on: tactile interaction, macro close-up, dramatic cinematic lighting (softbox, rim light, morning sun), shallow depth of field, fluid camera glide (gimbal push-in, tilt up).
- ALWAYS specify "vertical 9:16 format, photorealistic, 4k 60fps aesthetic".
- AVOID human faces/people in Kling B-roll to prevent safety filters and ensure pure cinematic product b-roll.

EXACT OUTPUT FORMAT:
[HOOK]
<spoken hook text only>

[SCENE_HOOK]
Visual Type: avatar
Characters: <character description, posture, authentic relatable emotion>
Scene Background: <location, realistic natural lighting, props>
Camera Movement: <handheld smartphone selfie, subtle micro-shake>
Movement in Scene: <leaning into camera, expressive reaction>
Sound Design: <spoken delivery nuance + ambient room tone>

[BODY]
<spoken body text only>

[SCENE_BODY]
Visual Type: b_roll
Kling Prompt: <cinematic prompt for Kling: product close-up, lighting, camera glide, vertical 9:16, 4k aesthetic>
Scene Background: <environment description and lighting>
Movement in Scene: <physical product motion or digital interface action>
Sound Design: <spoken delivery nuance + subtle foley sound effect>

[CTA]
<spoken cta text only>

[SCENE_CTA]
Visual Type: avatar
Characters: <character description, warm smiling expression, posture>
Scene Background: <location, warm lighting>
Camera Movement: <handheld smartphone, steady eye level>
Movement in Scene: <friendly nod, pointing down to link or smiling wave>
Sound Design: <warm enthusiastic delivery + concluding tone>"""


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
