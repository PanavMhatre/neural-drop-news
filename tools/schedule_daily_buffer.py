#!/usr/bin/env python3
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.buffer_client import BufferClient, build_post_text, build_service_text_map
from src.memory.database import Database
from src.public_media import public_assets_for_package


DAILY_SCHEDULE = [
    ("2026-06-01_duckduckgo-surges-as-users-flee-force-fed-ai-searc", "2026-06-02T09:00:00-05:00"),
    ("2026-06-01_qualcomm-agentic-ai-computex", "2026-06-02T10:30:00-05:00"),
    ("2026-06-01_motorola-dfend-counter-drone", "2026-06-02T12:00:00-05:00"),
    ("2026-06-01_anthropic-ipo-filing", "2026-06-02T13:30:00-05:00"),
    ("2026-06-01_softbank-france-ai-data-centers", "2026-06-02T15:00:00-05:00"),
]


def main() -> None:
    load_dotenv(ROOT / ".env")
    client = BufferClient()
    db = Database(str(ROOT / "data/news_shorts.db"))

    try:
        for package_id, due_at in DAILY_SCHEDULE:
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

            providers = ", ".join(f"{name}:{data['provider']}" for name, data in assets.items())
            print(f"scheduled {package_id} at {due_at} via {providers} to {len(posts)} Buffer channels")
    finally:
        db.close()


if __name__ == "__main__":
    main()
