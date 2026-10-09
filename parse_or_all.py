import urllib.request
import json
req = urllib.request.Request("https://openrouter.ai/api/v1/models")
with urllib.request.urlopen(req) as response:
    resp = json.loads(response.read().decode())
    for m in resp.get("data", []):
         j = json.dumps(m).lower()
         if '"video"' in j or 'video' in j:
             print(f'{m["id"]} | {m.get("name","")}')
