import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.buffer_client import BufferClient, BufferError, build_post_text, build_service_text_map
from src.memory.database import Database
from src.public_media import (
    PublicMediaError,
    already_scheduled_to_buffer,
    mark_scheduled_to_buffer,
    public_assets_for_package,
)

logger = logging.getLogger(__name__)


class AutoPublisher:
    """
    Background daemon that checks the scheduled_posts table and, when a
    post's time arrives, actually schedules it on Buffer (the same real
    publish path used by run_daily.py and the /api/schedule endpoint).
    """

    def __init__(self, check_interval_seconds: int = 60):
        self.check_interval = check_interval_seconds
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self.db = Database(db_path="./data/news_shorts.db")

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Auto-Publisher started.")

    def stop(self):
        self.is_running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("Auto-Publisher stopped.")

    def _publish_to_buffer(self, package_id: str, pkg_dir: Path, scheduled_time: str) -> bool:
        """Schedule a package's video on Buffer. Returns True on success."""
        prior = already_scheduled_to_buffer(pkg_dir)
        if prior:
            logger.info(f"Publisher: {package_id} already scheduled to Buffer at {prior.get('due_at')} — skipping")
            self.db.schedule_post(
                package_id, scheduled_time, status="buffer_scheduled",
                buffer_post_id=", ".join(prior.get("post_ids") or []),
                buffer_status="scheduled",
            )
            return True

        manifest = public_assets_for_package(pkg_dir)
        assets = manifest["assets"]
        if "video.mp4" not in assets:
            raise PublicMediaError(f"{package_id} has no uploaded video.mp4 asset")
        video_url = assets["video.mp4"]["url"]
        thumbnail_url = assets.get("thumbnail.png", {}).get("url")

        client = BufferClient()
        existing = client.find_existing_posts_for_video(video_url)
        if existing:
            mark_scheduled_to_buffer(pkg_dir, existing[0]["dueAt"], [p["id"] for p in existing])
            logger.info(f"Publisher: {package_id} already has Buffer posts — skipping")
            self.db.schedule_post(
                package_id, scheduled_time, status="buffer_scheduled",
                buffer_post_id=", ".join(p["id"] for p in existing),
                buffer_status="scheduled",
            )
            return True

        try:
            results = client.create_scheduled_video_posts(
                text=build_post_text(pkg_dir),
                text_by_service=build_service_text_map(pkg_dir),
                due_at=scheduled_time,
                video_url=video_url,
                thumbnail_url=thumbnail_url,
            )
        except BufferError as exc:
            # A failure partway through a multi-channel batch still leaves
            # earlier channels genuinely posted on Buffer — record those
            # (status=buffer_partial) instead of losing track of them, since
            # the outer except in run_once only sees this exception, not
            # exc.completed.
            if exc.completed:
                partial_post_ids = [r["post"]["id"] for r in exc.completed]
                partial_channels = [r["channel"] for r in exc.completed]
                partial_channel_names = [
                    f"{c.get('displayName') or c.get('name')} ({c.get('service')})" for c in partial_channels
                ]
                mark_scheduled_to_buffer(pkg_dir, scheduled_time, partial_post_ids)
                self.db.schedule_post(
                    package_id, scheduled_time, status="buffer_partial",
                    buffer_post_id=", ".join(partial_post_ids),
                    buffer_channel_id=", ".join(c["id"] for c in partial_channels),
                    buffer_channel_name=", ".join(partial_channel_names),
                    buffer_status="partial", buffer_error=str(exc),
                )
                logger.error(
                    f"Publisher: {package_id} partially scheduled on Buffer "
                    f"({', '.join(partial_channel_names)}) before failing: {exc}"
                )
            raise
        post_ids = [r["post"]["id"] for r in results]
        channels = [r["channel"] for r in results]
        channel_names = [f"{c.get('displayName') or c.get('name')} ({c.get('service')})" for c in channels]

        mark_scheduled_to_buffer(pkg_dir, scheduled_time, post_ids)
        self.db.schedule_post(
            package_id, scheduled_time, status="buffer_scheduled",
            buffer_post_id=", ".join(post_ids),
            buffer_channel_id=", ".join(c["id"] for c in channels),
            buffer_channel_name=", ".join(channel_names),
            buffer_status="scheduled",
        )
        logger.info(f"Publisher: {package_id} scheduled on Buffer -> {', '.join(channel_names)}")
        return True

    def run_once(self):
        """Check for due posts and publish them via Buffer."""
        try:
            scheduled_posts = self.db.get_scheduled_posts()
            now = datetime.now()

            for post in scheduled_posts:
                if post["status"] != "queued":
                    continue

                scheduled_time = datetime.fromisoformat(post["scheduled_time"])
                if now < scheduled_time:
                    continue

                package_id = post["package_id"]
                logger.info(f"Publisher: Time reached for {package_id}. Starting publish...")

                pkg_dir = None
                for base_dir in ["./output", "./demo/example_output"]:
                    d = Path(base_dir) / package_id
                    if (d / "video.mp4").exists():
                        pkg_dir = d
                        break

                if not pkg_dir:
                    logger.error(f"Publisher: video.mp4 not found for {package_id}")
                    self.db.update_schedule_status(package_id, "failed")
                    continue

                try:
                    self._publish_to_buffer(package_id, pkg_dir, post["scheduled_time"])
                except (BufferError, PublicMediaError) as exc:
                    logger.error(f"Publisher: Failed to publish {package_id}: {exc}")
                    self.db.schedule_post(
                        package_id, post["scheduled_time"],
                        status="buffer_failed", buffer_status="failed", buffer_error=str(exc),
                    )

        except Exception as e:
            logger.error(f"Publisher cycle failed: {e}")

    def _loop(self):
        while self.is_running:
            self.run_once()

            for _ in range(self.check_interval):
                if not self.is_running:
                    break
                time.sleep(1)
