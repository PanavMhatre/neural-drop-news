"""
YouTube channel analytics — pulls view/engagement data via YouTube Data API v3
to understand what's working and feed that into story scoring.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

YT_API_BASE = "https://www.googleapis.com/youtube/v3"
YT_ANALYTICS_BASE = "https://youtubeanalytics.googleapis.com/v2"


class YouTubeChannelAnalytics:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY", "")

    # ── Public channel stats (no OAuth needed) ──────────────────────────────

    def get_channel_id(self, handle_or_name: str) -> Optional[str]:
        """Resolve a channel handle (@NeuralDropBits) to a channel ID using forHandle."""
        handle = handle_or_name.lstrip("@")
        try:
            r = requests.get(
                f"{YT_API_BASE}/channels",
                params={
                    "key": self.api_key,
                    "forHandle": handle,
                    "part": "id",
                    "maxResults": 1,
                },
                timeout=10,
            )
            r.raise_for_status()
            items = r.json().get("items", [])
            if items:
                return items[0]["id"]
        except Exception as e:
            logger.warning(f"get_channel_id failed: {e}")
        return None

    def get_recent_videos(self, channel_id: str, max_results: int = 20) -> list[dict]:
        """Return recent video IDs + titles from a channel."""
        try:
            r = requests.get(
                f"{YT_API_BASE}/search",
                params={
                    "key": self.api_key,
                    "channelId": channel_id,
                    "part": "id,snippet",
                    "order": "date",
                    "type": "video",
                    "maxResults": max_results,
                },
                timeout=10,
            )
            r.raise_for_status()
            items = r.json().get("items", [])
            return [
                {
                    "video_id": i["id"]["videoId"],
                    "title": i["snippet"]["title"],
                    "published_at": i["snippet"]["publishedAt"],
                    "description": i["snippet"].get("description", ""),
                }
                for i in items
                if i.get("id", {}).get("videoId")
            ]
        except Exception as e:
            logger.warning(f"get_recent_videos failed: {e}")
            return []

    def get_video_stats(self, video_ids: list[str]) -> list[dict]:
        """Batch-fetch view/like/comment counts for up to 50 video IDs."""
        if not video_ids:
            return []
        try:
            r = requests.get(
                f"{YT_API_BASE}/videos",
                params={
                    "key": self.api_key,
                    "id": ",".join(video_ids[:50]),
                    "part": "statistics,snippet",
                },
                timeout=10,
            )
            r.raise_for_status()
            items = r.json().get("items", [])
            results = []
            for item in items:
                stats = item.get("statistics", {})
                results.append({
                    "video_id": item["id"],
                    "title": item["snippet"]["title"],
                    "views": int(stats.get("viewCount", 0)),
                    "likes": int(stats.get("likeCount", 0)),
                    "comments": int(stats.get("commentCount", 0)),
                    "published_at": item["snippet"]["publishedAt"],
                    "engagement_rate": self._engagement_rate(stats),
                })
            return results
        except Exception as e:
            logger.warning(f"get_video_stats failed: {e}")
            return []

    def _engagement_rate(self, stats: dict) -> float:
        views = int(stats.get("viewCount", 0))
        if views == 0:
            return 0.0
        return (int(stats.get("likeCount", 0)) + int(stats.get("commentCount", 0))) / views * 100

    # ── Insight extraction ───────────────────────────────────────────────────

    def get_performance_insights(self, channel_id: str) -> dict:
        """
        Return a structured insights dict: top topics, avg engagement,
        best performing keywords, ideal duration.
        Used by story scorer to boost relevant topics.
        """
        videos = self.get_recent_videos(channel_id, max_results=30)
        if not videos:
            return {}

        ids = [v["video_id"] for v in videos]
        stats = self.get_video_stats(ids)
        if not stats:
            return {}

        # Sort by views
        stats.sort(key=lambda x: x["views"], reverse=True)
        top5 = stats[:5]

        # Extract keywords from top video titles
        top_keywords: dict[str, float] = {}
        crypto_terms = [
            "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto",
            "etf", "defi", "regulation", "hack", "stablecoin", "mining",
            "institutional", "blackrock", "binance", "coinbase", "sec",
            "altcoin", "bull", "bear", "rally", "crash", "price",
        ]
        for v in top5:
            title_lower = v["title"].lower()
            for kw in crypto_terms:
                if kw in title_lower:
                    top_keywords[kw] = top_keywords.get(kw, 0) + v["views"]

        avg_views = sum(s["views"] for s in stats) / len(stats) if stats else 0
        avg_engagement = sum(s["engagement_rate"] for s in stats) / len(stats) if stats else 0

        return {
            "top_keywords": sorted(top_keywords.items(), key=lambda x: x[1], reverse=True)[:10],
            "avg_views_30d": avg_views,
            "avg_engagement_30d": avg_engagement,
            "top_videos": [{"title": v["title"], "views": v["views"]} for v in top5],
            "total_videos_analyzed": len(stats),
        }
