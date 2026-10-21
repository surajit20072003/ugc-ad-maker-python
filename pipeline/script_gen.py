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
- Raw, highly conversational, relatable creator speech delivered in a calm, natural, understated way (no hype voice). NOT a corporate TV commercial. Sounds like a friend sending a voice message or talking directly to their phone camera.
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

3. B-ROLL VISUAL LITERALISM RULE (MANDATORY):
Every B-roll visual MUST be a LITERAL physical representation of what the voiceover says at that moment.
- FORBIDDEN: Generic laptop / generic product shot unrelated to what is spoken.
- REQUIRED: If voiceover says "laggy website" → show buffering spinner, frozen cursor, loading bar stuck — NOT just a laptop.
- If voiceover says "fast results" → show a loading bar completing instantly or a counter rapidly incrementing.
- If voiceover says "secure" → show a padlock icon closing, or shield badge glowing.
- The viewer must understand the concept from the visual alone, without hearing audio.

4. KLING B-ROLL PROMPTS — STRUCTURED 3-FIELD FORMAT:
For [b_roll] segments, provide THREE separate fields (not one generic line):
a) Kling Prompt Start Frame: Describe the OPENING static frame in 50+ words. Include: exact object, material, surface texture, position in frame, lighting direction (e.g. "softbox from upper-left"), background. This is what the image model generates first.
b) Kling Prompt End Frame: Describe the CLOSING frame in 50+ words. Same background, same lighting, same angle — but showing product state AFTER the key action (revealed, opened, loaded, completed).
c) Kling Motion Prompt: Describe ONLY the physical movement between frames: what moves first, direction, speed. Use: "slow dolly push-in", "gimbal tilt-up", "locked static macro". End with: "No text overlays. Vertical 9:16. Photorealistic 4K."

5. B-ROLL BANNED WORDS (produce vague, generic AI output — DO NOT USE):
cinematic  beautiful  dynamic  abstract  stunning  elegant  seamless  dramatic  breathtaking  gorgeous  amazing

Instead use PHYSICAL SPECIFICS:
- Object: exact shape, material (matte aluminum, glossy acrylic, brushed steel), surface texture
- Light: "softbox from upper-left at 45 degrees, warm white 5500K"  
- Camera: "slow motorized gimbal dolly push-in 3cm over 8 seconds", "locked static macro lens"
- Action: "the loading bar advances left to right from 0% to 100%", "the lid rotates counter-clockwise 30 degrees"

6. ZERO-TEXT RULE (CRITICAL):
AI video models distort text into unreadable gibberish. NEVER ask to show text, brand names, slogans, labels, words, or typography. Always specify: "no visible text, no letters, no words, no watermark, no captions, sleek unbranded minimalist surface."

EXACT OUTPUT FORMAT:
[HOOK]
<spoken hook text only>

[SCENE_HOOK]
Visual Type: avatar
Characters: <character description, posture, authentic relatable emotion>
Scene Background: <location, realistic natural lighting, props>
Camera Movement: <handheld smartphone selfie, subtle micro-shake>
Movement in Scene: <very subtle natural movement: a small head nod or slight lean, calm reaction, minimal hand movement>
Sound Design: <spoken delivery nuance + ambient room tone>

[BODY]
<spoken body text only>

[SCENE_BODY]
Visual Type: b_roll
Kling Prompt Start Frame: <50+ word description of opening static frame: exact subject, material, position, lighting direction, background — must literally represent what voiceover says>
Kling Prompt End Frame: <50+ word description of closing frame: same background/lighting/angle, showing completed/revealed state>
Kling Motion Prompt: <physical movement description: what moves, direction, speed, camera name. End: "No text overlays. Vertical 9:16. Photorealistic 4K.">
Scene Background: <environment description and lighting>
Movement in Scene: <physical product motion or digital interface action>
Sound Design: <spoken delivery nuance + subtle foley sound effect>

[CTA]
<spoken cta text only>

[SCENE_CTA]
Visual Type: avatar
Characters: <character description, soft natural smile, relaxed posture>
Scene Background: <location, warm lighting>
Camera Movement: <handheld smartphone, steady eye level>
Movement in Scene: <small friendly nod, relaxed hands, no big gestures>
Sound Design: <warm, calm, sincere delivery + concluding tone>"""



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
            f"Note on Visuals: Keep B-roll video prompts strictly unbranded and zero-text (no readable letters or logos).\n"
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
