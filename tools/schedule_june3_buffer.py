#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.buffer_client import BufferClient, build_post_text, build_service_text_map
from src.memory.database import Database
from src.public_media import public_assets_for_package


JUNE3_SCHEDULE = [
    ("2026-06-02_kazakhstan-air-taxi-test", "2026-06-03T09:00:00-05:00"),
    ("2026-06-02_uber-munich-robotaxis", "2026-06-03T10:30:00-05:00"),
    ("2026-06-02_alphabet-ai-fundraising", "2026-06-03T12:00:00-05:00"),
    ("2026-06-02_anthropic-ipo-plans", "2026-06-03T13:30:00-05:00"),
    ("2026-06-02_baku-energy-week-ai", "2026-06-03T15:00:00-05:00"),
]


def main() -> None:
    load_dotenv(ROOT / ".env")
    client = BufferClient()
    db = Database(str(ROOT / "data/news_shorts.db"))

    try:
        for package_id, due_at in JUNE3_SCHEDULE:
            package_dir = ROOT / "output" / package_id
            if not (package_dir / "video.mp4").exists():
                raise SystemExit(f"Missing video.mp4 for {package_id}")

            manifest = public_assets_for_package(package_dir)
            assets = manifest["assets"]
            video_url = assets["video.mp4"]["url"]
            thumbnail_url = assets.get("thumbnail.png", {}).get("url")

            results = client.create_scheduled_video_posts(
                text=build_post_text(package_dir),
                text_by_service=build_service_text_map(package_dir),
                due_at=due_at,
                video_url=video_url,
                thumbnail_url=thumbnail_url,
            )
            posts = [result["post"] for result in results]
            channels = [result["channel"] for result in results]
            channel_names = [
                f"{channel.get('displayName') or channel.get('name')} ({channel.get('service')})"
                for channel in channels
            ]

            db.schedule_post(
                package_id,
                due_at,
                status="buffer_scheduled",
                buffer_post_id=", ".join(post["id"] for post in posts),
                buffer_channel_id=", ".join(channel["id"] for channel in channels),
                buffer_channel_name=", ".join(channel_names),
                buffer_status="scheduled",
            )

            print(f"scheduled {package_id} at {due_at} to {len(posts)} Buffer channels")
    finally:
        db.close()


if __name__ == "__main__":
    main()
