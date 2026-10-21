"""
pipeline/analyze.py
────────────────────
Claude Vision via OpenRouter: deep forensic product/scene analysis
(colors, typography, visible branding, packaging details) +
character consistency profile anchor generation for downstream video directing.
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
OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-sonnet-5"


def _build_headers() -> dict:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8765",
        "X-Title": "UGC Ad Maker Python",
    }


async def analyze_physical_product(
    image_url: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    image_mime: str = "image/jpeg",
) -> dict:
    """
    Forensic analysis of product image via Claude Vision (inspired by n8n workflow).
    Extracts brand, color scheme with HEX codes, visible text, packaging, and
    generates a locked character profile for visual consistency across all video segments.
    """
    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode()
        image_content = {
            "type": "image_url",
            "image_url": {"url": f"data:{image_mime};base64,{b64}"},
        }
    elif image_url:
        image_content = {"type": "image_url", "image_url": {"url": image_url}}
    else:
        return _fallback_physical_analysis()

    prompt = (
        "Perform a deep forensic analysis on this product image for an authentic UGC ad video production.\n"
        "Return ONLY a valid JSON object with the following fields:\n"
        "{\n"
        '  "brand_name": string (brand name if visible or inferred, else "Unknown"),\n'
        '  "color_scheme": [\n'
        '    {"hex": "#HEX", "name": "Color Name"}\n'
        "  ],\n"
        '  "font_style": string (typography/aesthetic feel of the label or packaging),\n'
        '  "visible_text": string (exact legible text visible on the bottle/box/product),\n'
        '  "product_type": string (beauty/supplement/skincare/food/beverage/tech/wearable/holdable/other),\n'
        '  "visual_description": string (concise 1-2 sentence description of physical look, texture, packaging finish),\n'
        '  "gender_target": string ("female" | "male" | "unisex"),\n'
        '  "character_profile": {\n'
        '    "description": string (locked description of a relatable 24-28yo UGC creator that fits this product perfectly - hair, skin, casual clothes, natural vibe),\n'
        '    "attire": string (everyday clothing that complements the product color palette),\n'
        '    "setting": string (authentic bedroom vanity, kitchen counter, or cozy living room with soft natural window light)\n'
        "  }\n"
        "}\n"
        "No explanation, no markdown backticks, only raw JSON."
    )

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    image_content,
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": 600,
        "temperature": 0.2,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(OPENROUTER_BASE, headers=_build_headers(), json=payload)
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()

        cleaned = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(cleaned)
        # Ensure fallback defaults if any keys missing
        if "character_profile" not in data:
            data["character_profile"] = _default_character_profile(data.get("gender_target", "unisex"))
        return data
    except Exception as exc:
        print(f"Warning: analyze_physical_product error ({exc}), using fallback.")
        return _fallback_physical_analysis()


async def analyze_software_product(product_name: str, product_benefit: str) -> dict:
    """
    For software / SaaS products: extracts audience, device, use case,
    and builds a locked creator profile.
    """
    prompt = (
        f"I'm producing a UGC testimonial ad for the software product: {product_name}.\n"
        f"Key Benefit: {product_benefit}\n\n"
        "Return ONLY a valid JSON object with the following fields:\n"
        "{\n"
        '  "brand_name": string,\n'
        '  "device_type": "laptop" | "phone" | "both",\n'
        '  "audience": string (2-3 word description of target user),\n'
        '  "use_case": string (one verb phrase describing what user does),\n'
        '  "visual_description": string (2-3 words for the software UI or screen scene),\n'
        '  "color_scheme": [\n'
        '    {"hex": "#2563EB", "name": "Tech Blue"},\n'
        '    {"hex": "#0F172A", "name": "Slate Navy"}\n'
        "  ],\n"
        '  "product_type": "software",\n'
        '  "gender_target": "unisex",\n'
        '  "character_profile": {\n'
        '    "description": string (authentic 25-30yo professional or creator at desk with laptop visible, natural candid demeanor),\n'
        '    "attire": string (casual modern workwear, e.g. neutral knit sweater or minimalist tee),\n'
        '    "setting": string (bright modern home office desk, warm ambient lighting, laptop screen in background)\n'
        "  }\n"
        "}\n"
        "No explanation, no markdown backticks, only raw JSON."
    )

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 500,
        "temperature": 0.2,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(OPENROUTER_BASE, headers=_build_headers(), json=payload)
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()

        cleaned = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(cleaned)
        data["product_type"] = "software"
        if "character_profile" not in data:
            data["character_profile"] = _default_character_profile("unisex", is_software=True)
        return data
    except Exception as exc:
        print(f"Warning: analyze_software_product error ({exc}), using fallback.")
        return {
            "brand_name": product_name,
            "device_type": "laptop",
            "audience": "modern professionals",
            "use_case": "streamline workflow",
            "visual_description": "software interface",
            "product_type": "software",
            "gender_target": "unisex",
            "color_scheme": [{"hex": "#2563EB", "name": "Blue"}],
            "character_profile": _default_character_profile("unisex", is_software=True),
        }


def _default_character_profile(gender: str = "unisex", is_software: bool = False) -> dict:
    if is_software:
        return {
            "description": "relatable 26-year-old creator with natural shoulder-length hair and a calm, friendly expression",
            "attire": "casual neutral ribbed crewneck sweater",
            "setting": "clean contemporary home office with laptop partially visible on desk, soft window light",
        }
    return {
        "description": "candid, natural 25-year-old creator with calm eyes, natural skin and effortless hairstyle",
        "attire": "casual comfortable oversized neutral cotton shirt",
        "setting": "brightly lit home bedroom vanity with soft natural daylight, cozy aesthetic",
    }


def _fallback_physical_analysis() -> dict:
    return {
        "brand_name": "Premium Brand",
        "gender_target": "unisex",
        "product_type": "holdable",
        "visual_description": "clean modern product packaging",
        "font_style": "minimalist sans-serif",
        "visible_text": "",
        "color_scheme": [{"hex": "#E2E8F0", "name": "Natural Neutral"}],
        "character_profile": _default_character_profile("unisex"),
    }
