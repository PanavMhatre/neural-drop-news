import os
import requests

key = "sk-hc-v1-c53f0e8d659c44b3a7b8e19b3c47178b5a753aee27da4e8aa826a2edd6c31dce"
base_url = "https://ai.hackclub.com/proxy/v1"

res = requests.get(f"{base_url}/models", headers={"Authorization": f"Bearer {key}"})
if res.status_code == 200:
    models = res.json()
    for m in models.get("data", []):
        if "gpt-4" in m.get("id", "").lower() or "grok" in m.get("id", "").lower():
            print(m.get("id"))
