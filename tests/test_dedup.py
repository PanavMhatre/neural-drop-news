"""Tests for dedup engine."""

import pytest
from src.memory.database import Database
from src.memory.dedup import DedupEngine
from src.models.schemas import RawStory


@pytest.fixture
def db(tmp_path):
    """Create a temporary database."""
    db = Database(db_path=str(tmp_path / "test.db"))
    yield db
    db.close()


@pytest.fixture
def dedup(db):
    return DedupEngine(db)


class TestDedupEngine:
    """Test dedup functionality."""

    def test_new_story_not_duplicate(self, dedup):
        story = RawStory(
            title="Brand New Story",
            url="https://example.com/new",
            source_name="Example",
            snippet="Test",
        )
        is_dup, reason = dedup.is_duplicate_story(story)
        assert not is_dup
        assert reason is None

    def test_exact_url_duplicate(self, dedup, db):
        story = RawStory(
            title="Test Story",
            url="https://example.com/test",
            source_name="Example",
            snippet="Test",
        )
        # Add to DB
        db.add_story(
            url_hash=story.url_hash,
            title_hash=story.title_hash,
            url=story.url,
            title=story.title,
            source_name=story.source_name,
        )

        is_dup, reason = dedup.is_duplicate_story(story)
        assert is_dup
        assert "URL" in reason

    def test_hook_not_overused_initially(self, dedup):
        is_overused, reason = dedup.is_hook_overused("This is a fresh hook")
        assert not is_overused

    def test_hook_overused_after_recording(self, dedup, db):
        hook = "This is my special hook"
        db.add_used_hook(hook, "testhash123")

        is_overused, reason = dedup.is_hook_overused("This is my special hook")
        assert is_overused

    def test_structure_rotation(self, dedup, db):
        structures = ["type_a", "type_b", "type_c"]

        # With no history, should pick randomly
        result = dedup.get_least_used_structure(structures)
        assert result in structures

        # After using type_a, should prefer type_b or type_c
        db.add_used_structure("type_a")
        result = dedup.get_least_used_structure(structures)
        assert result in ["type_b", "type_c"]


class TestDatabase:
    """Test database operations."""

    def test_story_exists(self, db):
        assert not db.story_exists("nonexistent")

        db.add_story(
            url_hash="test123",
            title_hash="title123",
            url="https://example.com",
            title="Test",
            source_name="Example",
        )

        assert db.story_exists("test123")

    def test_mark_processed(self, db):
        db.add_story(
            url_hash="proc123",
            title_hash="title123",
            url="https://example.com",
            title="Test",
            source_name="Example",
        )

        assert not db.was_story_processed("proc123")
        db.mark_story_processed("proc123")
        assert db.was_story_processed("proc123")

    def test_recent_hooks(self, db):
        db.add_used_hook("Hook 1", "hash1")
        db.add_used_hook("Hook 2", "hash2")

        hooks = db.get_recent_hooks(limit=5)
        assert len(hooks) == 2
        assert "Hook 2" in hooks

    def test_stats(self, db):
        stats = db.get_stats()
        assert "total_stories" in stats
        assert "total_videos" in stats
        assert stats["total_stories"] == 0
