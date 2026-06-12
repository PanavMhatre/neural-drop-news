"""Tests for story scoring."""

import pytest
from src.models.schemas import RawStory, StoryScore, StoryCategory
from src.discovery.sources import get_credibility_score, get_source_tier, SourceTier


class TestSourceCredibility:
    """Test source credibility registry."""

    def test_tier_1_source(self):
        score = get_credibility_score("Reuters")
        assert score == 90

    def test_tier_2_source(self):
        score = get_credibility_score("TechCrunch")
        assert score == 75

    def test_tier_3_source(self):
        score = get_credibility_score("Medium Blog")
        assert score == 50

    def test_unknown_source(self):
        score = get_credibility_score("Random Blog Nobody Heard Of")
        assert score == 35

    def test_source_url_matching(self):
        tier = get_source_tier("Some Article", "https://techcrunch.com/article")
        assert tier == SourceTier.TIER_2

    def test_case_insensitive(self):
        score = get_credibility_score("BLOOMBERG")
        assert score == 90


class TestStoryScore:
    """Test story score computation."""

    def test_total_score_calculation(self):
        score = StoryScore(
            freshness=100,
            source_credibility=100,
            relevance=100,
            viral_potential=100,
            educational_value=100,
            business_angle=100,
            visual_potential=100,
            explainability=100,
        )
        assert score.total_score == 100

    def test_weighted_score(self):
        score = StoryScore(
            freshness=80,
            source_credibility=90,
            relevance=70,
            viral_potential=60,
            educational_value=85,
            business_angle=75,
            visual_potential=50,
            explainability=80,
        )
        # Verify it's a reasonable weighted average
        assert 60 <= score.total_score <= 90

    def test_zero_score(self):
        score = StoryScore(
            freshness=0,
            source_credibility=0,
            relevance=0,
            viral_potential=0,
            educational_value=0,
            business_angle=0,
            visual_potential=0,
            explainability=0,
        )
        assert score.total_score == 0


class TestRawStory:
    """Test raw story model."""

    def test_url_hash_deterministic(self):
        story = RawStory(
            title="Test",
            url="https://example.com/test",
            source_name="Example",
            snippet="Test snippet",
        )
        hash1 = story.url_hash
        hash2 = story.url_hash
        assert hash1 == hash2

    def test_different_urls_different_hashes(self):
        story1 = RawStory(
            title="Test",
            url="https://example.com/test1",
            source_name="Example",
            snippet="Test",
        )
        story2 = RawStory(
            title="Test",
            url="https://example.com/test2",
            source_name="Example",
            snippet="Test",
        )
        assert story1.url_hash != story2.url_hash

    def test_title_hash(self):
        story = RawStory(
            title="  Test Title  ",
            url="https://example.com",
            source_name="Example",
            snippet="Test",
        )
        # Should normalize (lowercase + strip)
        assert len(story.title_hash) == 16
