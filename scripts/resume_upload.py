#!/usr/bin/env python3
"""One-off: upload+schedule already-built packages that failed during the pipeline run."""
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

from src.public_media import public_assets_for_package, already_scheduled_to_buffer, mark_scheduled_to_buffer
from src.buffer_client import BufferClient, build_post_text, build_service_text_map

root = Path(sys.argv[1])
package_dirs = sorted(p for p in root.iterdir() if p.is_dir() and (p / "video.mp4").exists())

client = BufferClient()
base_time = datetime.now(timezone.utc) + timedelta(hours=1)

for i, pkg_dir in enumerate(package_dirs):
    due_at = (base_time + timedelta(minutes=90 * i)).isoformat().replace("+00:00", "Z")

    prior = already_scheduled_to_buffer(pkg_dir)
    if prior:
        logger.info(f"⏭ {pkg_dir.name} already scheduled at {prior.get('due_at')} (posts: {prior.get('post_ids')}) — skipping")
        continue

    try:
        manifest = public_assets_for_package(pkg_dir)
        assets = manifest["assets"]
        video_url = assets["video.mp4"]["url"]
        thumbnail_url = assets.get("thumbnail.png", {}).get("url")

        existing = client.find_existing_posts_for_video(video_url)
        if existing:
            mark_scheduled_to_buffer(pkg_dir, existing[0]["dueAt"], [p["id"] for p in existing])
            logger.info(f"⏭ {pkg_dir.name} already scheduled on Buffer (found {len(existing)} post(s) for this video) — skipping")
            continue

        results = client.create_scheduled_video_posts(
            text=build_post_text(pkg_dir),
            text_by_service=build_service_text_map(pkg_dir),
            due_at=due_at,
            video_url=video_url,
            thumbnail_url=thumbnail_url,
        )
        channels = [r["channel"] for r in results]
        channel_names = [f"{c.get('displayName') or c.get('name')} ({c.get('service')})" for c in channels]
        mark_scheduled_to_buffer(pkg_dir, due_at, [r["post"]["id"] for r in results])
        logger.info(f"✓ {pkg_dir.name} → {due_at} → {', '.join(channel_names)}")
    except Exception as exc:
        logger.error(f"Failed to upload/schedule {pkg_dir.name}: {exc}", exc_info=True)
