#!/usr/bin/env python3
"""
Test android_vr and web_embedded clients — the two clients that require NO PO token
and NO cookies per yt-dlp wiki (updated Mar 2026).
All other clients (ios, android, web_creator, mweb) require PO tokens for GVS.
"""
import subprocess
import sys
from pathlib import Path

OUTPUT_DIR = Path("/tmp/yt_test")
OUTPUT_DIR.mkdir(exist_ok=True)

CONFIG_FILE = Path.home() / ".config/yt-dlp/config"
print(f"Config: {CONFIG_FILE}")
if CONFIG_FILE.exists():
    print(CONFIG_FILE.read_text())
print()

# Test each client independently so we know exactly which one works
CLIENTS = [
    "android_vr",       # No PO token required, no cookies needed
    "web_embedded",     # No PO token required (embeddable videos only)
]

# Channel-scoped ytsearch queries
QUERIES = [
    "ytsearch1:coin bureau crypto bitcoin",
    "ytsearch1:bankless podcast ethereum",
    "ytsearch1:altcoin daily crypto news",
]


def test_client(client: str, query: str, label: str) -> bool:
    cmd = [
        "yt-dlp",
        "-f", "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]/best[height<=720]/best",
        "-o", str(OUTPUT_DIR / f"{label}.%(ext)s"),
        "--no-playlist",
        "--extractor-args", f"youtube:player_client={client}",
        "--socket-timeout", "15",
        query,
    ]
    print(f"  [{client}] {query}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    stderr = result.stderr[-400:] if result.stderr else ""
    if result.returncode == 0:
        files = [f for f in OUTPUT_DIR.glob(f"{label}.*") if f.stat().st_size > 10_000]
        if files:
            print(f"  ✓ SUCCESS: {files[0].name} ({files[0].stat().st_size // 1024}KB)")
            return True
    # Show the last meaningful error line
    for line in reversed(stderr.splitlines()):
        line = line.strip()
        if line and not line.startswith("[debug]"):
            print(f"  ✗ {line[-120:]}")
            break
    return False


results = {}
for client in CLIENTS:
    print(f"\n{'='*50}")
    print(f"CLIENT: {client}")
    print('='*50)
    wins = 0
    for i, query in enumerate(QUERIES):
        label = f"{client}_{i}"
        if test_client(client, query, label):
            wins += 1
            break  # one success per client is enough proof
    results[client] = wins > 0
    print(f"  → {client}: {'WORKS ✓' if wins > 0 else 'BLOCKED ✗'}")

print(f"\n{'='*50}")
print("SUMMARY:")
for client, ok in results.items():
    print(f"  {client}: {'✓ WORKS' if ok else '✗ blocked'}")

sys.exit(0 if any(results.values()) else 1)
