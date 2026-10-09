import urllib.request
import json
req = urllib.request.Request("https://openrouter.ai/api/v1/models")
with urllib.request.urlopen(req) as response:
    resp = json.loads(response.read().decode())
    for m in resp.get("data", []):
        id = m.get("id", "").lower()
        if "sora" in id or "kling" in id or "luma" in id or "runway" in id or "minimax" in id or "haiper" in id or "rhymes" in id or "video" in id:
            print(m["id"])
