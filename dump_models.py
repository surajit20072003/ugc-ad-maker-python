import requests
import json
try:
    resp = requests.get("https://openrouter.ai/api/v1/models")
    models = resp.json().get("data", [])
    with open("all_models.txt", "w") as f:
        for m in models:
            f.write(m.get("id") + "\n")
except Exception as e:
    print(e)
