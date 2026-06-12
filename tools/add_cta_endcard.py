#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.video.cta import CTA_LINK, CTA_TEXT, make_cta_endcard

CHANNEL_CTA = f"Full AI briefing in bio -> Neural Drop\n{CTA_TEXT} -> {CTA_LINK}"
PLATFORM_CAPTIONS = {
    "tiktok": CHANNEL_CTA,
    "instagram": CHANNEL_CTA,
    "youtube": CHANNEL_CTA,
}


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=ROOT, check=True)


def add_cta_endcard(package_id: str) -> None:
    package = ROOT / "output" / package_id
    video = package / "video.mp4"
    if not video.exists():
        raise SystemExit(f"Missing video.mp4 for {package_id}")

    media = package / "media"
    media.mkdir(exist_ok=True)
    working_video = media / "video_before_cta.mp4"
    normalized_video = media / "video_before_cta_vertical.mp4"
    cta_png = media / "cta_endcard.png"
    cta_video = media / "cta_endcard.mp4"
    concat_file = media / "cta_concat.txt"

    if not working_video.exists():
        video.replace(working_video)
    run([
        "ffmpeg",
        "-y",
        "-i",
        str(working_video),
        "-vf",
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x04070c,"
        "setsar=1",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "48000",
        str(normalized_video),
    ])
    make_cta_endcard(cta_png)
    run([
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-t",
        "3",
        "-i",
        str(cta_png),
        "-f",
        "lavfi",
        "-t",
        "3",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-vf",
        "format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-shortest",
        str(cta_video),
    ])
    run([
        "ffmpeg",
        "-y",
        "-i",
        str(normalized_video),
        "-i",
        str(cta_video),
        "-filter_complex",
        "[0:v]fps=30,format=yuv420p[v0];"
        "[1:v]fps=30,format=yuv420p[v1];"
        "[0:a]aformat=sample_rates=48000:channel_layouts=stereo[a0];"
        "[1:a]aformat=sample_rates=48000:channel_layouts=stereo[a1];"
        "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]",
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(video),
    ])

    metadata_path = package / "metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
        metadata["cta"] = f"{CTA_TEXT} - {CTA_LINK}"
        description = metadata.get("description") or ""
        if CTA_LINK not in description:
            metadata["description"] = f"{description}\n\n{CTA_TEXT} -> {CTA_LINK}".strip()
        metadata["platform_captions"] = PLATFORM_CAPTIONS
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")

    sources_path = package / "sources.json"
    if sources_path.exists():
        sources = json.loads(sources_path.read_text())
        sources["cta"] = {
            "persistent_pill": sources.get("cta", {}).get("persistent_pill", False),
            "end_screen_seconds": 3,
            "text": CTA_TEXT,
            "link": CTA_LINK,
        }
        sources_path.write_text(json.dumps(sources, indent=2) + "\n")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: add_cta_endcard.py PACKAGE_ID [...]")
    for package_id in sys.argv[1:]:
        add_cta_endcard(package_id)


if __name__ == "__main__":
    main()
