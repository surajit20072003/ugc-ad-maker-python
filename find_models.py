import requests
import json
try:
    resp = requests.get("https://openrouter.ai/api/v1/models")
    models = resp.json().get("data", [])
    for m in models:
        id = m.get("id", "").lower()
        if "flux" in id or "gemini" in id or "dall" in id:
            print(m.get("id"))
except Exception as e:
    print(e)
