"""Tests for script structures and quality checks."""

import pytest
from src.scripts.structures import (
    SCRIPT_STRUCTURES,
    get_all_structure_types,
    get_structure,
    ScriptStructureType,
)
from src.models.schemas import (
    GeneratedScript,
    QualityCheck,
    QualityReport,
    QualityVerdict,
    ScriptSection,
    VisualCue,
)


class TestScriptStructures:
    """Test script structure system."""

    def test_all_structures_defined(self):
        """Every enum value should have a structure."""
        for st in ScriptStructureType:
            assert st in SCRIPT_STRUCTURES

    def test_get_all_structure_types(self):
        types = get_all_structure_types()
        assert len(types) == 7
        assert "sounds_boring_but" in types
        assert "headline_vs_reality" in types

    def test_structure_has_required_fields(self):
        for st, structure in SCRIPT_STRUCTURES.items():
            assert structure.name
            assert structure.hook_template
            assert structure.flow_description
            assert structure.example_hook
            assert structure.system_instruction

    def test_get_structure(self):
        structure = get_structure(ScriptStructureType.COMPANY_MOVE)
        assert structure.name == "Company Strategic Move"


class TestGeneratedScript:
    """Test generated script model."""

    def test_valid_script(self):
        script = GeneratedScript(
            sections=ScriptSection(
                hook="Test hook",
                main_explanation="Test explanation",
                why_it_matters="Test why it matters",
                student_dev_angle="Test angle",
                closing_line="Test closing",
            ),
            full_script="Full test script with enough words",
            word_count=100,
            estimated_duration_seconds=35,
            structure_type=ScriptStructureType.COMPANY_MOVE,
            visual_plan=[VisualCue(section="hook", description="Bold text")],
            caption_lines=["Test caption", "Another caption"],
            title_ideas=["Title 1", "Title 2", "Title 3"],
            description="Test description",
            hashtags=["#test"],
            source_list=["TechCrunch"],
            commentary_notes="Added analysis",
        )
        assert script.word_count == 100
        assert len(script.title_ideas) == 3

    def test_title_ideas_min_length(self):
        """Should require at least 3 title ideas."""
        with pytest.raises(Exception):
            GeneratedScript(
                sections=ScriptSection(
                    hook="h", main_explanation="m",
                    why_it_matters="w", student_dev_angle="s",
                    closing_line="c",
                ),
                full_script="Test",
                word_count=10,
                estimated_duration_seconds=5,
                structure_type=ScriptStructureType.COMPANY_MOVE,
                visual_plan=[],
                caption_lines=[],
                title_ideas=["Only one"],  # Too few
                description="d",
                hashtags=[],
                source_list=[],
                commentary_notes="n",
            )


class TestQualityReport:
    """Test quality report model."""

    def test_approved_report(self):
        report = QualityReport(
            verdict=QualityVerdict.APPROVED,
            overall_score=85,
            checks=[
                QualityCheck(name="test", passed=True, score=90, reason="Good"),
            ],
        )
        assert report.verdict == QualityVerdict.APPROVED

    def test_rejected_report(self):
        report = QualityReport(
            verdict=QualityVerdict.REJECTED,
            overall_score=30,
            checks=[
                QualityCheck(name="test", passed=False, score=20, reason="Bad"),
            ],
            suggested_fixes=["Fix something"],
        )
        assert report.verdict == QualityVerdict.REJECTED
        assert len(report.suggested_fixes) == 1
