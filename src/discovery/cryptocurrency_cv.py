"""
cryptocurrency.cv API client for real-time crypto news discovery.

Free, no API key required. Aggregates 200+ crypto news sources with
category filtering, a breaking-news feed (last 2h), and trending topics.

Base URL: https://cryptocurrency.cv
API docs: https://github.com/nirholas/cryptocurrency.cv
"""

import logging
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import quote

import requests

from src.models.schemas import RawStory, StoryCategory

logger = logging.getLogger(__name__)

BASE_URL = "https://cryptocurrency.cv"

# Endpoints polled in order of priority.
# Breaking news first (maximum freshness), then topic buckets that map
# directly to this channel's content pillars.
ENDPOINTS = [
    "/api/breaking?limit=20",                       # Last 2h — highest freshness score
    "/api/news?category=bitcoin&limit=10",
    "/api/news?category=ethereum&limit=10",
    "/api/news?category=institutional&limit=10",    # Strongest business_angle signal
    "/api/news?category=etf&limit=10",
    "/api/news?category=stablecoin&limit=10",
    "/api/news?category=defi&limit=10",
    "/api/news?category=regulation&limit=10",       # Maps to high viral_potential
    "/api/trending?limit=15",                       # Community trending topics
]


class CryptoCVClient:
    """Client for the cryptocurrency.cv free news API (no API key required)."""

    def __init__(self, config: dict):
        self.config = config
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "NeuralDropNews/1.0",
            "Accept": "application/json",
        })

    def search_stories(
        self,
        topic: Optional[str] = None,
        max_results: int = 40,
    ) -> list[RawStory]:
        """
        Fetch stories from cryptocurrency.cv.

        If a specific topic is supplied (e.g. from --topic CLI flag), the
        search endpoint is prepended so topic-scoped results come first.
        Otherwise the full category sweep runs.
        """
        endpoints = list(ENDPOINTS)
        if topic:
            endpoints.insert(0, f"/api/search?q={quote(topic)}&limit=20")

        all_stories: list[RawStory] = []
        seen_urls: set[str] = set()
        exclude = self.config.get("exclude_keywords", [])

        for endpoint in endpoints:
            if len(all_stories) >= max_results:
                break
            for story in self._fetch(endpoint):
                if story.url in seen_urls:
                    continue
                if any(kw.lower() in story.title.lower() for kw in exclude):
                    continue
                seen_urls.add(story.url)
                all_stories.append(story)
                if len(all_stories) >= max_results:
                    break

        logger.info(
            f"cryptocurrency.cv: {len(all_stories)} stories from {len(endpoints)} endpoints"
        )
        return all_stories

    def _fetch(self, endpoint: str) -> list[RawStory]:
        """Fetch and parse one endpoint, returning an empty list on any error."""
        try:
            resp = self._session.get(f"{BASE_URL}{endpoint}", timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"cryptocurrency.cv request failed ({endpoint}): {e}")
            return []
        except ValueError as e:
            logger.warning(f"cryptocurrency.cv parse error ({endpoint}): {e}")
            return []

        stories = []
        for item in data.get("articles", data.get("results", [])):
            story = self._parse(item)
            if story:
                stories.append(story)
        return stories

    def _parse(self, item: dict) -> Optional[RawStory]:
        """Parse one article dict into a RawStory."""
        try:
            title = item.get("title", "").strip()
            url = (item.get("link") or item.get("url") or "").strip()
            if not title or not url:
                return None

            # Published date — handle RFC 2822 and ISO 8601
            pub_date = None
            for field in ("pubDate", "publishedAt", "created_at"):
                raw = item.get(field)
                if not raw:
                    continue
                for parse in (
                    lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")),
                    parsedate_to_datetime,
                ):
                    try:
                        pub_date = parse(raw)
                        break
                    except (ValueError, TypeError):
                        pass
                if pub_date:
                    break

            # Source — API returns either a plain string or a dict
            src = item.get("source", "")
            if isinstance(src, dict):
                source_name = src.get("name") or src.get("title") or "Unknown"
                source_url = src.get("url")
            else:
                source_name = str(src) if src else "Unknown"
                source_url = None

            snippet = (item.get("description") or item.get("summary") or "")[:500] or title

            return RawStory(
                title=title,
                url=url,
                source_name=source_name,
                source_url=source_url,
                snippet=snippet,
                published_at=pub_date,
                image_url=item.get("image") or item.get("imageUrl") or item.get("urlToImage"),
                categories=[StoryCategory.GENERAL_TECH],
            )
        except Exception as e:
            logger.warning(f"Failed to parse cryptocurrency.cv article: {e}")
            return None
