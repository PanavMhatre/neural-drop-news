"""
NewsData.io API client for news discovery.

Searches for AI/tech stories using the NewsData.io API with configurable
topics, filtering, and error handling.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from src.models.schemas import RawStory, StoryCategory

logger = logging.getLogger(__name__)

NEWSDATA_BASE_URL = "https://newsdata.io/api/1/latest"

# Map search terms to story categories
TOPIC_CATEGORY_MAP = {
    "openai": StoryCategory.OPENAI,
    "anthropic": StoryCategory.ANTHROPIC,
    "google ai": StoryCategory.GOOGLE_AI,
    "meta ai": StoryCategory.META_AI,
    "apple ai": StoryCategory.APPLE_AI,
    "nvidia": StoryCategory.NVIDIA,
    "ai chip": StoryCategory.AI_CHIPS,
    "ai startup": StoryCategory.AI_STARTUPS,
    "ai funding": StoryCategory.AI_FUNDING,
    "developer tool": StoryCategory.DEVELOPER_TOOLS,
    "coding agent": StoryCategory.CODING_AGENTS,
    "software engineering": StoryCategory.SOFTWARE_ENGINEERING,
    "ai regulation": StoryCategory.AI_REGULATION,
    "product launch": StoryCategory.PRODUCT_LAUNCH,
    "tech layoff": StoryCategory.TECH_JOBS,
    "tech hiring": StoryCategory.TECH_JOBS,
}


class NewsDataClient:
    """Client for the NewsData.io API."""

    def __init__(self, api_key: str, config: dict):
        self.api_key = api_key
        self.config = config
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "TechPulseShorts/1.0"})

    def search_stories(
        self,
        topic: Optional[str] = None,
        max_results: int = 20,
    ) -> list[RawStory]:
        """
        Search for AI/tech news stories.

        Args:
            topic: Specific topic to search for. If None, searches all configured topics.
            max_results: Maximum number of stories to return.

        Returns:
            List of discovered stories.
        """
        if topic:
            topics = [topic]
        else:
            topics = self.config.get("search_topics", ["artificial intelligence"])

        all_stories: list[RawStory] = []
        seen_urls: set[str] = set()

        for search_topic in topics:
            if len(all_stories) >= max_results:
                break

            try:
                stories = self._search_single_topic(search_topic)
                for story in stories:
                    if story.url not in seen_urls and len(all_stories) < max_results:
                        seen_urls.add(story.url)
                        all_stories.append(story)
            except Exception as e:
                logger.warning(f"Failed to search topic '{search_topic}': {e}")
                continue

        logger.info(f"Discovered {len(all_stories)} stories across {len(topics)} topics")
        return all_stories

    def _search_single_topic(self, topic: str) -> list[RawStory]:
        """Search for a single topic."""
        params = {
            "apikey": self.api_key,
            "q": topic,
            "language": "en",
            "category": "technology,science",
            "size": 10,
        }

        # Add exclude keywords if configured
        exclude = self.config.get("exclude_keywords", [])
        if exclude:
            params["excludefield"] = "title"
            # NewsData doesn't have direct exclude, we'll filter in post-processing

        try:
            response = self._session.get(NEWSDATA_BASE_URL, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"NewsData API request failed: {e}")
            return []
        except ValueError as e:
            logger.error(f"Failed to parse NewsData response: {e}")
            return []

        if data.get("status") != "success":
            logger.error(f"NewsData API error: {data.get('message', 'Unknown error')}")
            return []

        articles = data.get("results", [])
        stories = []

        for article in articles:
            story = self._parse_article(article, topic)
            if story and self._passes_filters(story):
                stories.append(story)

        return stories

    def _parse_article(self, article: dict[str, Any], search_topic: str) -> Optional[RawStory]:
        """Parse a NewsData article into a RawStory."""
        try:
            title = article.get("title", "").strip()
            url = article.get("link", "").strip()

            if not title or not url:
                return None

            # Parse published date
            pub_date = None
            pub_str = article.get("pubDate") or article.get("pubDateTZ")
            if pub_str:
                try:
                    pub_date = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

            # Detect categories
            categories = self._detect_categories(title, search_topic)

            return RawStory(
                title=title,
                url=url,
                source_name=article.get("source_name", article.get("source_id", "Unknown")),
                source_url=article.get("source_url"),
                snippet=article.get("description", article.get("content", ""))[:500],
                published_at=pub_date,
                image_url=article.get("image_url"),
                categories=categories,
                raw_data=article,
            )
        except Exception as e:
            logger.warning(f"Failed to parse article: {e}")
            return None

    def _detect_categories(self, title: str, search_topic: str) -> list[StoryCategory]:
        """Detect story categories from title and search topic."""
        categories = []
        combined = f"{title} {search_topic}".lower()

        for keyword, category in TOPIC_CATEGORY_MAP.items():
            if keyword in combined and category not in categories:
                categories.append(category)

        if not categories:
            categories.append(StoryCategory.GENERAL_AI)

        return categories

    def _passes_filters(self, story: RawStory) -> bool:
        """Check if a story passes basic quality filters."""
        exclude_keywords = self.config.get("exclude_keywords", [])

        # Check title against exclude keywords
        title_lower = story.title.lower()
        for keyword in exclude_keywords:
            if keyword.lower() in title_lower:
                logger.debug(f"Filtered out (exclude keyword '{keyword}'): {story.title[:60]}")
                return False

        # Must have a snippet/description
        if not story.snippet or len(story.snippet.strip()) < 20:
            logger.debug(f"Filtered out (no snippet): {story.title[:60]}")
            return False

        return True
