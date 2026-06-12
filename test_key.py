import os
import requests

key = "sk-hc-v1-c53f0e8d659c44b3a7b8e19b3c47178b5a753aee27da4e8aa826a2edd6c31dce"
print("Testing Hack Club AI API...")
res = requests.get("https://ai.hackclub.com/proxy/v1/models", headers={"Authorization": f"Bearer {key}"})
print(f"Status: {res.status_code}")
if res.status_code == 200:
    models = res.json()
    for m in models.get("data", [])[:5]:
        print(f" - {m.get('id')}")
