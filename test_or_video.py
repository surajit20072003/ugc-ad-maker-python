import requests
import json
resp = requests.get("https://openrouter.ai/api/v1/models").json()
for m in resp.get("data", []):
    modalities = m.get("architecture", {}).get("modality", "")
    if "video" in modalities.lower():
        print(m["id"], "-", modalities)
        
