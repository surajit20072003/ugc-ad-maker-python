import httpx
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("OPENROUTER_API_KEY")

async def test():
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "UGC Ad Maker Python",
    }
    payload = {
        "model": "kwaivgi/kling-video-o1",
        "prompt": "Person looking directly at camera...",
        "image": "http://204.12.237.78:8765/uploads/image_imggen.jpg",
        "aspect_ratio": "9:16",
        "duration": 8
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://openrouter.ai/api/v1/videos", headers=headers, json=payload)
        print("Status:", resp.status_code)
        print("Response:", resp.text)

asyncio.run(test())
