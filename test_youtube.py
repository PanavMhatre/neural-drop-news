#!/usr/bin/env python3
"""
Test: ytsearch-based download exactly like OpenClips.
One yt-dlp call handles search + download — no YouTube Data API, no video ID lookup.
"""
import subprocess
import sys
from pathlib import Path

OUTPUT_DIR = Path("/tmp/yt_test")
OUTPUT_DIR.mkdir(exist_ok=True)

CONFIG_FILE = Path.home() / ".config/yt-dlp/config"
print(f"Config: {CONFIG_FILE} — exists={CONFIG_FILE.exists()}")
if CONFIG_FILE.exists():
    print(CONFIG_FILE.read_text())
print()

CHANNEL_QUERIES = [
    "ytsearch1:coin bureau crypto",
    "ytsearch1:benjamin cowen into the cryptoverse",
    "ytsearch1:bankless podcast crypto",
    "ytsearch1:altcoin daily crypto",
    "ytsearch1:decrypt crypto news",
]


def try_ytsearch(query: str, label: str) -> bool:
    out = str(OUTPUT_DIR / f"{label}.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f", "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]/best[height<=720]/best",
        "-o", out,
        "--no-playlist",
        "--extractor-args", "youtube:player_client=ios,android,web_creator",
        "--socket-timeout", "15",
        "--match-filter", "duration > 600",
        query,
    ]
    print(f"  cmd: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"  stderr tail: {result.stderr[-300:].strip()}")
    if result.returncode == 0:
        files = [f for f in OUTPUT_DIR.glob(f"{label}.*") if f.stat().st_size > 10_000]
        if files:
            print(f"  ✓ {files[0].name} ({files[0].stat().st_size // 1024} KB)")
            return True
    print(f"  ✗ exit {result.returncode}")
    return False


success = 0
for i, query in enumerate(CHANNEL_QUERIES):
    print(f"\n[{query}]")
    if try_ytsearch(query, f"v{i}"):
        success += 1

print(f"\n{'='*50}")
print(f"Result: {success}/{len(CHANNEL_QUERIES)} succeeded")
sys.exit(0 if success > 0 else 1)
