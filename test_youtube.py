#!/usr/bin/env python3
"""
Diagnostic: YouTube API v3 search → yt-dlp download.
Cookies and sleep config are auto-read from ~/.config/yt-dlp/
No cookiefile or extractor_args passed — yt-dlp handles it automatically.
"""
import os
import sys
from pathlib import Path

import requests
import yt_dlp

API_KEY = os.getenv("YOUTUBE_API_KEY", "")
OUTPUT_DIR = Path("/tmp/yt_test")
OUTPUT_DIR.mkdir(exist_ok=True)

COOKIE_FILE = Path.home() / ".config/yt-dlp/cookies.txt"
CONFIG_FILE = Path.home() / ".config/yt-dlp/config"

print(f"Cookie file: {COOKIE_FILE} — exists={COOKIE_FILE.exists()}, lines={len(COOKIE_FILE.read_text().splitlines()) if COOKIE_FILE.exists() else 0}")
print(f"Config file: {CONFIG_FILE} — exists={CONFIG_FILE.exists()}")
if COOKIE_FILE.exists():
    yt_lines = [l for l in COOKIE_FILE.read_text().splitlines() if "youtube" in l.lower()]
    print(f"YouTube cookie entries: {len(yt_lines)}")
print()

QUERIES = [
    "Bitcoin price drop crypto news",
    "BlackRock Bitcoin ETF news",
]


def search_youtube(query: str) -> str | None:
    if not API_KEY:
        print("  No YOUTUBE_API_KEY — skipping API search")
        return None
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={"key": API_KEY, "q": query, "part": "snippet", "type": "video",
                "maxResults": 1, "videoDuration": "short", "order": "relevance"},
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


def download_video(video_id: str, label: str) -> bool:
    url = f"https://www.youtube.com/watch?v={video_id}"
    # No cookiefile, no extractor_args — yt-dlp reads ~/.config/yt-dlp/cookies.txt
    # and ~/.config/yt-dlp/config automatically
    opts = {
        "format": "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": str(OUTPUT_DIR / f"{label}.%(ext)s"),
        "noplaylist": True,
        "quiet": False,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        files = list(OUTPUT_DIR.glob(f"{label}.*"))
        mp4s = [f for f in files if f.suffix == ".mp4"]
        target = mp4s[0] if mp4s else (files[0] if files else None)
        if target and target.stat().st_size > 10_000:
            print(f"  ✓ Downloaded: {target.name} ({target.stat().st_size // 1024} KB)")
            return True
        print(f"  ✗ File missing or too small after download")
        return False
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return False


success = 0
for i, query in enumerate(QUERIES):
    print(f"--- {query} ---")
    video_id = search_youtube(query)
    if not video_id:
        print("  ✗ No video ID from API")
        continue
    if download_video(video_id, f"clip_{i}"):
        success += 1
    print()

print(f"Result: {success}/{len(QUERIES)} succeeded")
sys.exit(0 if success > 0 else 1)
