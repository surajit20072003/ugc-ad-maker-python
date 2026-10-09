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
    "prompt": "A small cute cat",
    "model": "black-forest-labs/flux-1.1-pro"
}

for url in ["https://openrouter.ai/api/v1/images/generations", "https://openrouter.ai/api/v1/images", "https://openrouter.ai/api/v1/chat/completions"]:
    print(f"Testing {url}...")
    try:
        resp = requests.post(url, headers=headers, json=payload)
        print("Status:", resp.status_code)
        print("Response:", resp.text[:200])
    except Exception as e:
        print("Error:", e)
    print("-" * 40)
