"""
Dedup engine — prevents duplicate and near-duplicate content.

Checks:
  - Exact URL dedup
  - Title similarity (fuzzy matching)
  - Content hash matching
  - Hook phrase repetition
  - Structure type rotation
  - Visual template rotation
"""

import hashlib
import logging
from typing import Optional

from rapidfuzz import fuzz

from src.memory.database import Database
from src.models.schemas import RawStory

logger = logging.getLogger(__name__)

# Similarity threshold for title fuzzy matching (0-100)
TITLE_SIMILARITY_THRESHOLD = 85


class DedupEngine:
    """Prevents duplicate stories, hooks, and visual repetition."""

    def __init__(self, db: Database):
        self.db = db

    def is_duplicate_story(self, story: RawStory) -> tuple[bool, Optional[str]]:
        """
        Check if a story is a duplicate.

        Returns:
            (is_duplicate, reason) — reason is None if not a duplicate.
        """
        # 1. Exact URL match
        if self.db.story_exists(story.url_hash):
            return True, "Exact URL already seen"

        # 2. Already processed (same title hash)
        if self.db.title_similar_exists(story.title_hash):
            return True, "Story with identical title already processed"

        # 3. Fuzzy title match against recent processed stories
        # We check the last 200 story titles for similarity
        conn = self.db._get_connection()
        rows = conn.execute(
            "SELECT title FROM stories WHERE processed = 1 ORDER BY discovered_at DESC LIMIT 200"
        ).fetchall()

        for row in rows:
            similarity = fuzz.ratio(story.title.lower(), row["title"].lower())
            if similarity >= TITLE_SIMILARITY_THRESHOLD:
                return True, f"Title too similar to existing story ({similarity}% match): '{row['title'][:60]}...'"

        return False, None

    def is_hook_overused(self, hook_text: str, max_recent: int = 15) -> tuple[bool, Optional[str]]:
        """
        Check if a hook phrase is too similar to recently used hooks.

        Returns:
            (is_overused, reason)
        """
        recent_hooks = self.db.get_recent_hooks(limit=max_recent)

        for used_hook in recent_hooks:
            similarity = fuzz.ratio(hook_text.lower(), used_hook.lower())
            if similarity >= 80:
                return True, f"Hook too similar to recent: '{used_hook[:50]}...' ({similarity}%)"

        return False, None

    def get_least_used_structure(self, available_structures: list[str]) -> str:
        """
        Pick the script structure that has been used least recently.

        Falls back to random if none have been used.
        """
        recent = self.db.get_recent_structures(limit=len(available_structures) * 2)

        if not recent:
            import random
            return random.choice(available_structures)

        # Find structures NOT in recent list
        unused = [s for s in available_structures if s not in recent]
        if unused:
            import random
            return random.choice(unused)

        # All have been used — pick the one used longest ago
        # (last in the recent list = used longest ago)
        for structure in reversed(recent):
            if structure in available_structures:
                return structure

        import random
        return random.choice(available_structures)

    def get_least_used_template(
        self,
        available_templates: list[str],
        available_colors: list[tuple[int, int, int]],
    ) -> tuple[str, tuple[int, int, int]]:
        """
        Pick the visual template + color combo that has been used least recently.
        """
        import random

        recent = self.db.get_recent_templates(limit=len(available_templates) * len(available_colors))
        recent_combos = set(recent)

        # Try to find an unused combination
        all_combos = [
            (t, c) for t in available_templates for c in available_colors
        ]
        random.shuffle(all_combos)

        for template, color in all_combos:
            color_str = str(color)
            if (template, color_str) not in recent_combos:
                return template, color

        # All used — pick randomly
        template = random.choice(available_templates)
        color = random.choice(available_colors)
        return template, color

    def record_usage(
        self,
        story: RawStory,
        hook_text: str,
        structure_type: str,
        template_type: str,
        accent_color: tuple[int, int, int],
        score_total: Optional[int] = None,
        score_data: Optional[dict] = None,
    ) -> None:
        """Record all usage data after a video is generated."""
        # Record story
        self.db.add_story(
            url_hash=story.url_hash,
            title_hash=story.title_hash,
            url=story.url,
            title=story.title,
            source_name=story.source_name,
            published_at=story.published_at.isoformat() if story.published_at else None,
            score_total=score_total,
            score_data=score_data,
            accepted=True,
        )
        self.db.mark_story_processed(story.url_hash)

        # Record hook
        hook_hash = hashlib.sha256(hook_text.lower().encode()).hexdigest()[:16]
        self.db.add_used_hook(hook_text, hook_hash)

        # Record structure and template
        self.db.add_used_structure(structure_type)
        self.db.add_used_template(template_type, str(accent_color))

        logger.info(f"Recorded usage for story: {story.title[:60]}...")
