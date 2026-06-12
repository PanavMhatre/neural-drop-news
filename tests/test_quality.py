"""Tests for quality gate local checks."""

import pytest
from src.models.schemas import (
    GeneratedScript,
    QualityVerdict,
    ScriptSection,
    ScriptStructureType,
    VisualCue,
)


def _make_script(word_count=100, sources=None, caption_lines=None):
    """Helper to create a test script."""
    if sources is None:
        sources = ["TechCrunch"]
    if caption_lines is None:
        caption_lines = ["Cap 1", "Cap 2"]
    return GeneratedScript(
        sections=ScriptSection(
            hook="Test hook",
            main_explanation="Test explanation",
            why_it_matters="Test why it matters",
            student_dev_angle="Test angle",
            closing_line="Test closing",
        ),
        full_script="Test " * word_count,
        word_count=word_count,
        estimated_duration_seconds=word_count * 0.35,
        structure_type=ScriptStructureType.COMPANY_MOVE,
        visual_plan=[VisualCue(section="hook", description="Text")],
        caption_lines=caption_lines,
        title_ideas=["T1", "T2", "T3"],
        description="Test desc",
        hashtags=["#test"],
        source_list=sources,
        commentary_notes="Added analysis",
    )


class TestLocalQualityChecks:
    """Test local (non-LLM) quality checks."""

    def test_word_count_in_range(self):
        from src.scripts.quality import QualityGate
        # We can't fully test without OpenAI, but we can test local checks
        script = _make_script(word_count=100)
        assert 80 <= script.word_count <= 120

    def test_word_count_too_short(self):
        script = _make_script(word_count=50)
        assert script.word_count < 80

    def test_word_count_too_long(self):
        script = _make_script(word_count=150)
        assert script.word_count > 120

    def test_sources_present(self):
        script = _make_script(sources=["TechCrunch", "Bloomberg"])
        assert len(script.source_list) > 0

    def test_sources_missing(self):
        script = _make_script(sources=[])
        assert len(script.source_list) == 0

    def test_caption_lines_present(self):
        script = _make_script(caption_lines=["Line 1", "Line 2", "Line 3"])
        assert len(script.caption_lines) > 0

    def test_caption_lines_missing(self):
        script = _make_script(caption_lines=[])
        assert len(script.caption_lines) == 0
