#!/usr/bin/env python3
"""
Test: channel-targeted YouTube search + yt-dlp download (ios,android,web_creator, no cookies).
Searches within known crypto channels from the roster, tests if those videos download.
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
print(f"Config: {CONFIG_FILE} — exists={CONFIG_FILE.exists()}")
if CONFIG_FILE.exists():
    print(CONFIG_FILE.read_text())
print()

# Weighted channels: (search_alias, weight)
CHANNELS = [
    ("coin bureau crypto",              3),
    ("benjamin cowen cryptoverse",      3),
    ("altcoin daily crypto",            3),
    ("bankless podcast crypto",         3),
    ("investanswers crypto",            2),
    ("decrypt crypto news",             2),
    ("real vision crypto",              2),
    ("unchained laura shin crypto",     2),
    ("crypto banter show",              2),
]

TOPIC = "bitcoin etf news"


def search_channel(channel_alias: str, topic: str) -> list[tuple[str, str]]:
    if not API_KEY:
        return []
    q = f"{topic} {channel_alias}"
    print(f"  Searching: {q!r}")
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "key": API_KEY, "q": q,
            "part": "snippet", "type": "video",
            "maxResults": 2, "videoDuration": "medium",
            "order": "relevance",
        },
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    return [(i["id"]["videoId"], i["snippet"]["title"]) for i in items
            if "#shorts" not in i["snippet"]["title"].lower()]


def try_download(video_id: str, label: str) -> bool:
    url = f"https://www.youtube.com/watch?v={video_id}"
    out = str(OUTPUT_DIR / f"{label}.%(ext)s")
    cmd = [
        "yt-dlp", "-f",
        "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]/best[height<=720]/best",
        "-o", out, "--no-playlist",
        "--extractor-args", "youtube:player_client=ios,android,web_creator",
        "--socket-timeout", "15",
        url,
    ]
    print(f"    yt-dlp {video_id} ...", end=" ", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        files = [f for f in OUTPUT_DIR.glob(f"{label}.*") if f.stat().st_size > 10_000]
        if files:
            print(f"✓ {files[0].stat().st_size // 1024}KB")
            return True
    stderr_tail = result.stderr[-200:] if result.stderr else ""
    print(f"✗  {stderr_tail.strip()[-80:]}")
    return False


success = 0
tried = 0
for channel_alias, _ in CHANNELS[:6]:  # test top 6 channels
    print(f"\n[{channel_alias}]")
    candidates = search_channel(channel_alias, TOPIC)
    if not candidates:
        print("  no results")
        continue
    for vid, title in candidates:
        tried += 1
        print(f"  [{vid}] {title}")
        if try_download(vid, f"v{tried}"):
            success += 1
            break  # one success per channel is enough

print(f"\n{'='*50}")
print(f"Result: {success}/{len(CHANNELS[:6])} channels got a download ({tried} videos tried)")
sys.exit(0 if success > 0 else 1)
