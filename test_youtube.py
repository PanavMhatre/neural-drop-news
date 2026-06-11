#!/usr/bin/env python3
"""
Diagnostic: YouTube Data API v3 search → yt-dlp web client + cookies download.
No TTS, no rendering, no Buffer.
"""
import os
import sys
from pathlib import Path

import requests
import yt_dlp

API_KEY = os.getenv("YOUTUBE_API_KEY", "")
COOKIES_FILE = os.getenv("YOUTUBE_COOKIES_FILE", "/home/runner/.config/yt-dlp/cookies.txt")
OUTPUT_DIR = Path("/tmp/yt_test")
OUTPUT_DIR.mkdir(exist_ok=True)

QUERIES = [
    "Bitcoin price drop crypto news",
    "BlackRock Bitcoin ETF news",
]

# ── Diagnose cookie file ──────────────────────────────────────────────────────
cookie_path = Path(COOKIES_FILE)
print(f"Cookie file path: {COOKIES_FILE}")
print(f"Cookie file exists: {cookie_path.exists()}")
if cookie_path.exists():
    size = cookie_path.stat().st_size
    lines = cookie_path.read_text().splitlines()
    print(f"Cookie file size: {size} bytes, {len(lines)} lines")
    # Print first non-comment line to verify format
    for line in lines:
        if line.strip() and not line.startswith("#"):
            parts = line.split("\t")
            print(f"First cookie entry: domain={parts[0] if parts else '?'}, name={parts[5] if len(parts) > 5 else '?'}")
            break
    # Count youtube.com cookies
    yt_cookies = [l for l in lines if "youtube.com" in l or ".youtube.com" in l]
    print(f"YouTube cookies: {len(yt_cookies)}")
else:
    print("ERROR: cookie file missing!")
    sys.exit(1)
print()

# ── YouTube API search ────────────────────────────────────────────────────────
def search_youtube(query: str) -> str | None:
    if not API_KEY:
        return None
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "key": API_KEY,
            "q": query,
            "part": "snippet",
            "type": "video",
            "maxResults": 1,
            "videoDuration": "short",
            "order": "relevance",
        },
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if items:
        vid = items[0]["id"]["videoId"]
        title = items[0]["snippet"]["title"]
        print(f"  API found: [{vid}] {title}")
        return vid
    return None


# ── yt-dlp download — web client + cookies ────────────────────────────────────
def download_video(video_id: str, label: str) -> bool:
    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {
        "format": "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": str(OUTPUT_DIR / f"{label}.%(ext)s"),
        "noplaylist": True,
        "quiet": False,
        "cookiefile": COOKIES_FILE,
        # Use web client — the one that actually uses browser cookies
        "extractor_args": {"youtube": {"player_client": ["web"]}},
        "retries": 3,
        "sleep_interval": 2,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        files = list(OUTPUT_DIR.glob(f"{label}.*"))
        if files and files[0].stat().st_size > 10_000:
            print(f"  ✓ Downloaded: {files[0].name} ({files[0].stat().st_size // 1024} KB)")
            return True
        print(f"  ✗ File missing or too small")
        return False
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return False


# ── Run ───────────────────────────────────────────────────────────────────────
success = 0
for i, query in enumerate(QUERIES):
    print(f"--- {query} ---")
    video_id = search_youtube(query)
    if not video_id:
        print("  ✗ API returned no results")
        continue
    if download_video(video_id, f"clip_{i}"):
        success += 1
    print()

print(f"Result: {success}/{len(QUERIES)} succeeded")
sys.exit(0 if success > 0 else 1)
