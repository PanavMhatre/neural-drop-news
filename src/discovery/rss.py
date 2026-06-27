"""
RSS feed fallback client for news discovery.

Provides an alternative news source using curated tech RSS feeds
when the NewsData.io API is unavailable or quota is exhausted.
"""

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import feedparser

from src.models.schemas import RawStory, StoryCategory

logger = logging.getLogger(__name__)

# Curated list of tech/AI RSS feeds
RSS_FEEDS = [
    {
        "name": "TechCrunch",
        "url": "https://techcrunch.com/feed/",
        "categories": [StoryCategory.AI_STARTUPS, StoryCategory.GENERAL_TECH],
    },
    {
        "name": "The Verge - AI",
        "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "categories": [StoryCategory.GENERAL_AI],
    },
    {
        "name": "Ars Technica - AI",
        "url": "https://feeds.arstechnica.com/arstechnica/technology-lab",
        "categories": [StoryCategory.GENERAL_AI, StoryCategory.GENERAL_TECH],
    },
    {
        "name": "VentureBeat",
        "url": "https://venturebeat.com/feed/",
        "categories": [StoryCategory.AI_STARTUPS, StoryCategory.AI_FUNDING],
    },
    {
        "name": "MIT Technology Review",
        "url": "https://www.technologyreview.com/feed/",
        "categories": [StoryCategory.GENERAL_AI],
    },
    {
        "name": "Hacker News (Top)",
        "url": "https://hnrss.org/frontpage",
        "categories": [StoryCategory.DEVELOPER_TOOLS, StoryCategory.SOFTWARE_ENGINEERING],
    },
    {
        "name": "Google AI Blog",
        "url": "https://blog.google/technology/ai/rss/",
        "categories": [StoryCategory.GOOGLE_AI],
    },
    {
        "name": "OpenAI Blog",
        "url": "https://openai.com/blog/rss.xml",
        "categories": [StoryCategory.OPENAI],
    },
    # ── Crypto / Digital-asset feeds (fallback when NewsData.io is unavailable) ──
    {
        "name": "CoinDesk",
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "categories": [StoryCategory.GENERAL_TECH],
    },
    {
        "name": "CoinTelegraph",
        "url": "https://cointelegraph.com/rss",
        "categories": [StoryCategory.GENERAL_TECH],
    },
    {
        "name": "Decrypt",
        "url": "https://decrypt.co/feed",
        "categories": [StoryCategory.GENERAL_TECH],
    },
    {
        "name": "The Block",
        "url": "https://www.theblock.co/rss.xml",
        "categories": [StoryCategory.GENERAL_TECH],
    },
    {
        "name": "Bitcoin Magazine",
        "url": "https://bitcoinmagazine.com/.rss/full/",
        "categories": [StoryCategory.GENERAL_TECH],
    },
    {
        "name": "Blockworks",
        "url": "https://blockworks.co/feed",
        "categories": [StoryCategory.GENERAL_TECH],
    },
    {
        "name": "Unchained Crypto",
        "url": "https://unchainedcrypto.com/feed/",
        "categories": [StoryCategory.GENERAL_TECH],
    },
    {
        "name": "CryptoSlate",
        "url": "https://cryptoslate.com/feed/",
        "categories": [StoryCategory.GENERAL_TECH],
    },
    {
        "name": "Crypto Briefing",
        "url": "https://cryptobriefing.com/feed/",
        "categories": [StoryCategory.GENERAL_TECH],
    },
]


class RSSClient:
    """RSS feed reader for tech/AI news."""

    def __init__(self, config: dict):
        self.config = config
        self._feeds = RSS_FEEDS

    def search_stories(
        self,
        topic: Optional[str] = None,
        max_results: int = 20,
    ) -> list[RawStory]:
        """
        Fetch stories from RSS feeds.

        Args:
            topic: If provided, filter entries matching this topic.
            max_results: Maximum stories to return.

        Returns:
            List of discovered stories.
        """
        all_stories: list[RawStory] = []
        seen_urls: set[str] = set()

        for feed_info in self._feeds:
            if len(all_stories) >= max_results:
                break

            try:
                stories = self._fetch_feed(feed_info, topic)
                for story in stories:
                    if story.url not in seen_urls and len(all_stories) < max_results:
                        seen_urls.add(story.url)
                        all_stories.append(story)
            except Exception as e:
                logger.warning(f"Failed to fetch RSS feed '{feed_info['name']}': {e}")
                continue

        logger.info(f"Discovered {len(all_stories)} stories from {len(self._feeds)} RSS feeds")
        return all_stories

    def _fetch_feed(self, feed_info: dict, topic: Optional[str] = None) -> list[RawStory]:
        """Fetch and parse a single RSS feed."""
        feed = feedparser.parse(feed_info["url"])

        if feed.bozo and not feed.entries:
            logger.warning(f"RSS parse error for {feed_info['name']}: {feed.bozo_exception}")
            return []

        stories = []
        exclude_keywords = self.config.get("exclude_keywords", [])

        for entry in feed.entries[:10]:  # Limit per feed
            story = self._parse_entry(entry, feed_info)
            if story is None:
                continue

            # Topic filter
            if topic and topic.lower() not in story.title.lower() and topic.lower() not in story.snippet.lower():
                continue

            # Exclude keyword filter
            title_lower = story.title.lower()
            if any(kw.lower() in title_lower for kw in exclude_keywords):
                continue

            stories.append(story)

        return stories

    def _parse_entry(self, entry: dict, feed_info: dict) -> Optional[RawStory]:
        """Parse an RSS entry into a RawStory."""
        try:
            title = entry.get("title", "").strip()
            url = entry.get("link", "").strip()

            if not title or not url:
                return None

            # Parse published date
            pub_date = None
            if "published_parsed" in entry and entry.published_parsed:
                try:
                    pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    pass
            elif "published" in entry:
                try:
                    pub_date = parsedate_to_datetime(entry.published)
                except (TypeError, ValueError):
                    pass

            # Get snippet
            snippet = entry.get("summary", entry.get("description", ""))
            # Strip HTML tags (basic)
            import re
            snippet = re.sub(r"<[^>]+>", "", snippet)[:500]

            return RawStory(
                title=title,
                url=url,
                source_name=feed_info["name"],
                source_url=entry.get("link", ""),
                snippet=snippet,
                published_at=pub_date,
                image_url=self._extract_image(entry),
                categories=feed_info.get("categories", [StoryCategory.GENERAL_TECH]),
            )
        except Exception as e:
            logger.warning(f"Failed to parse RSS entry: {e}")
            return None

    def _extract_image(self, entry: dict) -> Optional[str]:
        """Try to extract an image URL from an RSS entry."""
        # Check media content
        if "media_content" in entry:
            for media in entry.media_content:
                if "url" in media:
                    return media["url"]

        # Check enclosures
        if "enclosures" in entry:
            for enc in entry.enclosures:
                if enc.get("type", "").startswith("image"):
                    return enc.get("href")

        return None
