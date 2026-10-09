import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("OPENROUTER_API_KEY")

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

payload = {
    "prompt": "Person looking directly at camera, speaking naturally",
    "image": "http://204.12.237.78:8765/uploads/image_imggen.jpg",
    "model": "kwaivgi/kling-video-o1",
    "aspect_ratio": "9:16",
    "duration": 5
}

resp = requests.post("https://openrouter.ai/api/v1/videos", headers=headers, json=payload)
print("Status:", resp.status_code)
print("Response:", resp.text)
