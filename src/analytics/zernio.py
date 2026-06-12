"""
Zernio analytics client — tracks video events and pulls performance data.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

ZERNIO_BASE = "https://api.zernio.com/v1"
_API_KEY = os.getenv("ZERNIO_API_KEY", "sk_a96058cb3a56f11d5660669cf233e83234cefada02d853397401684c1c03d076")


def _headers() -> dict:
    return {"Authorization": f"Bearer {_API_KEY}", "Content-Type": "application/json"}


def track_video_published(
    video_id: str,
    title: str,
    story_topic: str,
    broll_source: str,          # "youtube" | "pixabay" | "motion_graphics"
    duration_seconds: float,
    quality_score: int,
    platform: str = "buffer",   # "instagram" | "tiktok" | "youtube_shorts"
) -> bool:
    """Fire a 'video_published' event to Zernio."""
    payload = {
        "event": "video_published",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "properties": {
            "video_id": video_id,
            "title": title,
            "story_topic": story_topic,
            "broll_source": broll_source,
            "duration_seconds": duration_seconds,
            "quality_score": quality_score,
            "platform": platform,
        },
    }
    try:
        r = requests.post(f"{ZERNIO_BASE}/events", json=payload, headers=_headers(), timeout=10)
        r.raise_for_status()
        logger.info(f"Zernio: tracked video_published for '{title[:50]}'")
        return True
    except Exception as e:
        logger.warning(f"Zernio track failed: {e}")
        return False


def get_top_performing(
    metric: str = "views",
    days: int = 30,
    limit: int = 10,
) -> list[dict]:
    """
    Return top-performing videos by metric over the last N days.
    metric: "views" | "engagement_rate" | "watch_time"
    """
    try:
        r = requests.get(
            f"{ZERNIO_BASE}/analytics/top",
            params={"metric": metric, "days": days, "limit": limit},
            headers=_headers(),
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        logger.warning(f"Zernio top_performing failed: {e}")
        return []


def get_topic_performance() -> dict[str, float]:
    """
    Return a map of story_topic → avg engagement score for use in story scoring.
    Falls back to empty dict if Zernio is unreachable.
    """
    try:
        r = requests.get(
            f"{ZERNIO_BASE}/analytics/topics",
            headers=_headers(),
            timeout=10,
        )
        r.raise_for_status()
        items = r.json().get("data", [])
        return {item["topic"]: float(item.get("avg_engagement", 0)) for item in items}
    except Exception as e:
        logger.warning(f"Zernio topic_performance failed: {e}")
        return {}
