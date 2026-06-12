#!/usr/bin/env python3
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.buffer_client import (
    BufferClient,
    build_post_text,
    build_service_text_map,
    canonical_buffer_service,
)
from src.memory.database import Database
from src.public_media import public_assets_for_package


REQUIRED_SERVICES = {"instagram", "tiktok", "youtube"}

JUNE7_SCHEDULE = [
    ("2026-06-07_bitcoin-rough-patch", "2026-06-07T20:45:00-05:00"),
    ("2026-06-07_ethereum-collapse-pressure", "2026-06-07T22:15:00-05:00"),
    ("2026-06-07_mastercard-onchain-settlement", "2026-06-07T23:45:00-05:00"),
    ("2026-06-07_clarity-act-delay", "2026-06-08T09:00:00-05:00"),
    ("2026-06-07_lawmakers-crypto-holdings", "2026-06-08T10:30:00-05:00"),
]


def service_set(channels: list[dict]) -> set[str]:
    return {canonical_buffer_service(channel.get("service")) for channel in channels}


def channel_label(channel: dict) -> str:
    name = channel.get("displayName") or channel.get("name") or "unnamed"
    service = canonical_buffer_service(channel.get("service"))
    return f"{name} ({service})"


def main() -> None:
    load_dotenv(ROOT / ".env")
    client = BufferClient()
    target_channels = client.resolve_target_channels()
    target_services = service_set(target_channels)
    missing_targets = REQUIRED_SERVICES - target_services
    if missing_targets:
        raise SystemExit(
            "Buffer target check failed; missing services: "
            + ", ".join(sorted(missing_targets))
        )

    print("resolved Buffer targets:")
    for channel in target_channels:
        print(f"- {channel_label(channel)} {channel.get('id')}")

    db = Database(str(ROOT / "data/news_shorts.db"))
    try:
        for package_id, due_at in JUNE7_SCHEDULE:
            package_dir = ROOT / "output" / package_id
            video_path = package_dir / "video.mp4"
            if not video_path.exists():
                raise SystemExit(f"Missing video.mp4 for {package_id}")

            text_by_service = build_service_text_map(package_dir)
            missing_captions = REQUIRED_SERVICES - set(text_by_service)
            if missing_captions:
                raise SystemExit(
                    f"{package_id} is missing platform captions for: "
                    + ", ".join(sorted(missing_captions))
                )

            manifest = public_assets_for_package(package_dir)
            assets = manifest.get("assets") or {}
            video_url = (assets.get("video.mp4") or {}).get("url")
            thumbnail_url = (assets.get("thumbnail.png") or {}).get("url")
            if not video_url:
                raise SystemExit(f"Missing public video URL for {package_id}")

            results = client.create_scheduled_video_posts(
                text=build_post_text(package_dir),
                text_by_service=text_by_service,
                due_at=due_at,
                video_url=video_url,
                thumbnail_url=thumbnail_url,
            )
            posts = [result["post"] for result in results]
            channels = [result["channel"] for result in results]
            posted_services = service_set(channels)
            missing_posts = REQUIRED_SERVICES - posted_services
            if missing_posts:
                raise SystemExit(
                    f"{package_id} Buffer scheduling was incomplete; missing: "
                    + ", ".join(sorted(missing_posts))
                )

            channel_names = [channel_label(channel) for channel in channels]
            db.schedule_post(
                package_id,
                due_at,
                status="buffer_scheduled",
                buffer_post_id=", ".join(post["id"] for post in posts),
                buffer_channel_id=", ".join(channel["id"] for channel in channels),
                buffer_channel_name=", ".join(channel_names),
                buffer_status="scheduled",
            )

            providers = ", ".join(
                f"{name}:{data['provider']}" for name, data in assets.items()
            )
            print(
                f"scheduled {package_id} at {due_at} to "
                f"{', '.join(sorted(posted_services))} via {providers}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
