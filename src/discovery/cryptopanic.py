"""
CryptoPanic API client for trending crypto news discovery.

CryptoPanic aggregates stories from 100+ crypto publications and ranks them
by community vote volume (bullish/bearish/important). Pulling the "hot" and
"rising" filters gives a direct signal for viral_potential — the community
has already decided these stories are worth engaging with.

Free API docs: https://cryptopanic.com/developers/api/
Sign up at https://cryptopanic.com to get an auth_token (free tier).
Set env var: CRYPTOPANIC_API_KEY=<your_token>
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import requests

from src.models.schemas import RawStory, StoryCategory

logger = logging.getLogger(__name__)

CRYPTOPANIC_BASE_URL = "https://cryptopanic.com/api/free/v1/posts/"


class CryptoPanicClient:
    """Client for the CryptoPanic trending news aggregator."""

    def __init__(self, api_key: str, config: dict):
        self.api_key = api_key
        self.config = config
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "NeuralDropNews/1.0"})

    def search_stories(
        self,
        topic: Optional[str] = None,
        max_results: int = 20,
    ) -> list[RawStory]:
        """
        Fetch trending crypto stories from CryptoPanic.

        Pulls "hot" then "rising" stories for diversity. Topic and exclude
        filters are applied client-side since the free API doesn't support
        server-side keyword filtering.
        """
        all_stories: list[RawStory] = []
        seen_urls: set[str] = set()

        for filter_type in ("hot", "rising"):
            if len(all_stories) >= max_results:
                break
            fetched = self._fetch(filter_type)
            for story in fetched:
                if story.url not in seen_urls and len(all_stories) < max_results:
                    seen_urls.add(story.url)
                    all_stories.append(story)

        # Topic filter (client-side)
        if topic:
            topic_lower = topic.lower()
            all_stories = [
                s for s in all_stories
                if topic_lower in s.title.lower() or topic_lower in s.snippet.lower()
            ]

        # Exclude keyword filter
        exclude = self.config.get("exclude_keywords", [])
        all_stories = [
            s for s in all_stories
            if not any(kw.lower() in s.title.lower() for kw in exclude)
        ]

        logger.info(f"CryptoPanic: {len(all_stories)} trending stories after filters")
        return all_stories

    def _fetch(self, filter_type: str) -> list[RawStory]:
        """Fetch one page of results for a given filter (hot / rising / important)."""
        params = {
            "auth_token": self.api_key,
            "public": "true",
            "filter": filter_type,
        }

        try:
            response = self._session.get(
                CRYPTOPANIC_BASE_URL, params=params, timeout=15
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"CryptoPanic API request failed ({filter_type}): {e}")
            return []
        except ValueError as e:
            logger.error(f"Failed to parse CryptoPanic response: {e}")
            return []

        stories = []
        for item in data.get("results", []):
            story = self._parse_item(item)
            if story:
                stories.append(story)

        return stories

    def _parse_item(self, item: dict) -> Optional[RawStory]:
        """Parse a CryptoPanic result into a RawStory."""
        try:
            title = item.get("title", "").strip()
            url = item.get("url", "").strip()

            if not title or not url:
                return None

            # Publication date
            pub_date = None
            for date_field in ("published_at", "created_at"):
                pub_str = item.get(date_field)
                if pub_str:
                    try:
                        pub_date = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                        break
                    except (ValueError, TypeError):
                        pass

            # Source metadata
            source = item.get("source", {})
            source_name = source.get("title", "Unknown")
            source_domain = source.get("domain", "")

            # Community vote signal — included in snippet so scorer can weight it
            votes = item.get("votes", {})
            positive = votes.get("positive", 0)
            negative = votes.get("negative", 0)
            total = positive + negative
            vote_note = f" [{positive}↑ {negative}↓ on CryptoPanic]" if total > 0 else ""
            snippet = f"{source_name}: {title}{vote_note}"

            return RawStory(
                title=title,
                url=url,
                source_name=source_name,
                source_url=f"https://{source_domain}" if source_domain else None,
                snippet=snippet[:500],
                published_at=pub_date,
                image_url=None,
                categories=[StoryCategory.GENERAL_TECH],
            )
        except Exception as e:
            logger.warning(f"Failed to parse CryptoPanic item: {e}")
            return None
