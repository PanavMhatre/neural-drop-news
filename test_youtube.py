#!/usr/bin/env python3
"""Diagnostic: test yt-dlp YouTube search with cookies. No TTS, no rendering, no Buffer."""
import os
import sys
from pathlib import Path

import yt_dlp

COOKIES_FILE = os.getenv("YOUTUBE_COOKIES_FILE", "/tmp/yt_cookies.txt")
OUTPUT_DIR = Path("/tmp/yt_test")
OUTPUT_DIR.mkdir(exist_ok=True)

QUERIES = [
    "ytsearch1:Bitcoin price drop crypto news",
    "ytsearch1:BlackRock Bitcoin ETF news",
]

cookies_ok = Path(COOKIES_FILE).exists() and Path(COOKIES_FILE).stat().st_size > 100
print(f"Cookie file: {COOKIES_FILE}")
print(f"Cookie file exists: {Path(COOKIES_FILE).exists()}")
print(f"Cookie file size: {Path(COOKIES_FILE).stat().st_size if Path(COOKIES_FILE).exists() else 0} bytes")
print(f"Cookie file first line: {open(COOKIES_FILE).readline().strip() if cookies_ok else 'N/A'}")
print()

opts = {
    "format": "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    "outtmpl": str(OUTPUT_DIR / "%(id)s.%(ext)s"),
    "noplaylist": True,
    "quiet": False,
    "no_warnings": False,
    "socket_timeout": 30,
}
if cookies_ok:
    opts["cookiefile"] = COOKIES_FILE
    print("Using cookies file for yt-dlp")
else:
    print("WARNING: no valid cookie file — running without cookies")

print()
success = 0
for query in QUERIES:
    print(f"--- Testing: {query} ---")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(query, download=True)
            entries = info.get("entries") or [info]
            entry = entries[0] if entries else info
            ext = entry.get("ext", "mp4")
            vid_id = entry.get("id", "unknown")
            out = OUTPUT_DIR / f"{vid_id}.{ext}"
            if out.exists():
                print(f"✓ Downloaded: {out} ({out.stat().st_size // 1024} KB)")
                success += 1
            else:
                # try glob
                files = list(OUTPUT_DIR.glob(f"*.{ext}"))
                if files:
                    print(f"✓ Downloaded: {files[0]} ({files[0].stat().st_size // 1024} KB)")
                    success += 1
                else:
                    print(f"✗ File not found after download")
    except Exception as e:
        print(f"✗ FAILED: {e}")
    print()

print(f"Result: {success}/{len(QUERIES)} queries succeeded")
sys.exit(0 if success > 0 else 1)
