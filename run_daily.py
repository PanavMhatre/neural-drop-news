#!/usr/bin/env python3
"""
Daily pipeline runner: discover → render → upload → schedule to Buffer.
Called by GitHub Actions on cron schedule.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main(count: int = 7, topic: str | None = None, manifest: str | None = None, skip_buffer: bool = False) -> None:
    import json
    from src.pipeline import Pipeline
    from src.public_media import public_assets_for_package
    from src.buffer_client import BufferClient, build_post_text, build_service_text_map

    pipeline = Pipeline()

    # If the cloud curator sent a pre-selected manifest, inject those URLs as topics
    if manifest:
        stories = json.loads(manifest)
        logger.info(f"Manifest provided: {len(stories)} pre-selected stories")
        packages = []
        for story in stories[:count]:
            url = story.get("video_url") or story.get("article_url")
            pkgs = pipeline.generate(topic=url, count=1)
            packages.extend(pkgs)
    else:
        logger.info(f"Starting daily pipeline: count={count}, topic={topic or 'auto'}")
        packages = pipeline.generate(topic=topic, count=count)

    if not packages:
        logger.error("Pipeline produced no packages — exiting with failure")
        sys.exit(1)

    if skip_buffer:
        logger.info(f"Generated {len(packages)} packages — Buffer skipped (diagnostic mode)")
        for p in packages:
            logger.info(f"  Package: {p.package_id} → {p.output_dir}")
        return

    logger.info(f"Generated {len(packages)} packages — uploading and scheduling")

    client = BufferClient()
    # Space posts 90 minutes apart, first one goes out 1 hour from now
    base_time = datetime.now(timezone.utc) + timedelta(hours=1)

    for i, package in enumerate(packages):
        pkg_dir = Path(package.output_dir)
        due_at = (base_time + timedelta(minutes=90 * i)).isoformat().replace("+00:00", "Z")

        try:
            manifest = public_assets_for_package(pkg_dir)
            assets = manifest["assets"]
            video_url = assets["video.mp4"]["url"]
            thumbnail_url = assets.get("thumbnail.png", {}).get("url")

            results = client.create_scheduled_video_posts(
                text=build_post_text(pkg_dir),
                text_by_service=build_service_text_map(pkg_dir),
                due_at=due_at,
                video_url=video_url,
                thumbnail_url=thumbnail_url,
            )
            channels = [r["channel"] for r in results]
            channel_names = [
                f"{c.get('displayName') or c.get('name')} ({c.get('service')})"
                for c in channels
            ]
            logger.info(
                f"✓ {package.package_id} → {due_at} → {', '.join(channel_names)}"
            )
        except Exception as exc:
            logger.error(f"Failed to upload/schedule {package.package_id}: {exc}", exc_info=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run daily news pipeline")
    parser.add_argument("--count", type=int, default=5, help="Number of clips to generate")
    parser.add_argument("--topic", type=str, default=None, help="Optional topic override")
    parser.add_argument("--manifest", type=str, default=None, help="JSON manifest from cloud curator")
    parser.add_argument("--skip-buffer", action="store_true", help="Skip Buffer scheduling (diagnostic/test runs)")
    args = parser.parse_args()
    main(count=args.count, topic=args.topic, manifest=args.manifest, skip_buffer=args.skip_buffer)
