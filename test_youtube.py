#!/usr/bin/env python3
"""
Diagnostic: test YouTube download from GitHub Actions using ios,android,web_creator
client chain via yt-dlp binary. No cookies needed.
"""
import os
import subprocess
import sys
from pathlib import Path

import requests

API_KEY = os.getenv("YOUTUBE_API_KEY", "")
OUTPUT_DIR = Path("/tmp/yt_test")
OUTPUT_DIR.mkdir(exist_ok=True)

CONFIG_FILE = Path.home() / ".config/yt-dlp/config"
print(f"Config file: {CONFIG_FILE} — exists={CONFIG_FILE.exists()}")
if CONFIG_FILE.exists():
    print(f"Config contents:\n{CONFIG_FILE.read_text()}")
print()

QUERIES = [
    "Bitcoin price crypto news 2024",
    "Ethereum blockchain technology explained",
    "crypto market update today",
]


def search_youtube(query: str, max_results: int = 5) -> list[tuple[str, str]]:
    if not API_KEY:
        print("  No YOUTUBE_API_KEY")
        return []
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={"key": API_KEY, "q": query, "part": "snippet", "type": "video",
                "maxResults": max_results, "videoDuration": "short", "order": "relevance"},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    return [(item["id"]["videoId"], item["snippet"]["title"]) for item in items]


def download_video(video_id: str, label: str) -> bool:
    url = f"https://www.youtube.com/watch?v={video_id}"
    out_tmpl = str(OUTPUT_DIR / f"{label}.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f", "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]/best[height<=720]/best",
        "-o", out_tmpl,
        "--no-playlist",
        "--extractor-args", "youtube:player_client=ios,android,web_creator",
        "--socket-timeout", "15",
        "--verbose",
        url,
    ]
    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print(f"  ✗ yt-dlp exited {result.returncode}")
        return False
    files = list(OUTPUT_DIR.glob(f"{label}.*"))
    mp4s = [f for f in files if f.suffix == ".mp4"]
    target = mp4s[0] if mp4s else (files[0] if files else None)
    if target and target.stat().st_size > 10_000:
        print(f"  ✓ Downloaded: {target.name} ({target.stat().st_size // 1024} KB)")
        return True
    print(f"  ✗ File missing or too small")
    return False


success = 0
for i, query in enumerate(QUERIES):
    print(f"--- {query} ---")
    candidates = search_youtube(query, max_results=5)
    if not candidates:
        print("  ✗ No candidates from API")
        continue
    got_one = False
    for video_id, title in candidates:
        print(f"  Trying [{video_id}] {title}")
        if download_video(video_id, f"clip_{i}"):
            success += 1
            got_one = True
            break
    if not got_one:
        print(f"  ✗ All {len(candidates)} candidates failed")
    print()

print(f"Result: {success}/{len(QUERIES)} queries succeeded")
sys.exit(0 if success > 0 else 1)
