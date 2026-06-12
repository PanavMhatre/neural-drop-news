import os
import requests

import os
key = os.environ.get("OPENAI_API_KEY", "")
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
