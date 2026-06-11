#!/usr/bin/env python3
"""
Diagnostic: YouTube Data API v3 search → yt-dlp android client download.
No TTS, no rendering, no Buffer.
"""
import os
import sys
from pathlib import Path

import requests
import yt_dlp

API_KEY = os.getenv("YOUTUBE_API_KEY", "")
OUTPUT_DIR = Path("/tmp/yt_test")
OUTPUT_DIR.mkdir(exist_ok=True)

QUERIES = [
    "Bitcoin price drop crypto news",
    "BlackRock Bitcoin ETF news",
]

print(f"YouTube API key set: {bool(API_KEY)}")
print()

def search_youtube(query: str) -> str | None:
    """Use YouTube Data API v3 to find best video ID for a query."""
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "key": API_KEY,
            "q": query,
            "part": "snippet",
            "type": "video",
            "maxResults": 1,
            "videoDuration": "short",  # under 4 minutes
            "order": "relevance",
        },
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        return None
    video_id = items[0]["id"]["videoId"]
    title = items[0]["snippet"]["title"]
    print(f"  API found: [{video_id}] {title}")
    return video_id


def download_video(video_id: str, section: str) -> bool:
    """Download via yt-dlp using Android player client (bypasses bot detection)."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    out_path = str(OUTPUT_DIR / f"{section}.%(ext)s")
    opts = {
        "format": "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": out_path,
        "noplaylist": True,
        "quiet": False,
        # Android client bypasses bot detection — no cookies needed
        "extractor_args": {"youtube": {"player_client": ["android"]}},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        files = list(OUTPUT_DIR.glob(f"{section}.*"))
        if files and files[0].stat().st_size > 10_000:
            print(f"  ✓ Downloaded: {files[0].name} ({files[0].stat().st_size // 1024} KB)")
            return True
        print(f"  ✗ File missing or empty after download")
        return False
    except Exception as e:
        print(f"  ✗ yt-dlp failed: {e}")
        return False


success = 0
for i, query in enumerate(QUERIES):
    print(f"--- Query: {query} ---")
    video_id = search_youtube(query)
    if not video_id:
        print("  ✗ API returned no results")
        continue
    if download_video(video_id, f"clip_{i}"):
        success += 1
    print()

print(f"Result: {success}/{len(QUERIES)} succeeded")
sys.exit(0 if success > 0 else 1)
