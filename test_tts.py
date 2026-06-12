import os
import requests

key = "sk-hc-v1-c53f0e8d659c44b3a7b8e19b3c47178b5a753aee27da4e8aa826a2edd6c31dce"
base_url = "https://ai.hackclub.com/proxy/v1"

print("Testing TTS...")
try:
    res = requests.post(
        f"{base_url}/audio/speech",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "tts-1",
            "input": "Test audio.",
            "voice": "alloy"
        }
    )
    print(f"TTS Status: {res.status_code}")
except Exception as e:
    print(f"TTS Error: {e}")
