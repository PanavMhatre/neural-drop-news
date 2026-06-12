import os
import requests

import os
key = os.environ.get("OPENAI_API_KEY", "")
print("Testing Hack Club AI API...")
res = requests.get("https://ai.hackclub.com/proxy/v1/models", headers={"Authorization": f"Bearer {key}"})
print(f"Status: {res.status_code}")
if res.status_code == 200:
    models = res.json()
    for m in models.get("data", [])[:5]:
        print(f" - {m.get('id')}")
