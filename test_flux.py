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
    "model": "black-forest-labs/flux.2-pro"
}

resp = requests.post("https://openrouter.ai/api/v1/images", headers=headers, json=payload)
print(resp.status_code)
print(resp.text[:500])
