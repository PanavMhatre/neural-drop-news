import os
import requests

import os
key = os.environ.get("OPENAI_API_KEY", "")
base_url = "https://ai.hackclub.com/proxy/v1"

res = requests.get(f"{base_url}/models", headers={"Authorization": f"Bearer {key}"})
if res.status_code == 200:
    models = res.json()
    for m in models.get("data", []):
        if "gpt-4" in m.get("id", "").lower() or "grok" in m.get("id", "").lower():
            print(m.get("id"))
