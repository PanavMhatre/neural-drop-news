"""
Quality gate for script validation.

Runs multiple checks before allowing a script to proceed to
voiceover and rendering. Can trigger revision or rejection.
"""

import logging
from typing import Optional

from openai import OpenAI

from src.models.schemas import (
    GeneratedScript,
    LLMQualityCheck,
    QualityCheck,
    QualityReport,
    QualityVerdict,
    ScoredStory,
)

logger = logging.getLogger(__name__)

QUALITY_SYSTEM_PROMPT = """You are a content quality reviewer for a YouTube Shorts channel about AI and tech news.

Your job is to evaluate whether a script is ready for production or needs revision.

The channel targets students, developers, and people interested in AI/tech.
Videos should add ORIGINAL COMMENTARY — not just read news articles.

Evaluate the script against these criteria:

1. is_just_summary: Is this script merely summarizing an article without adding original perspective?
2. has_original_commentary: Does the script add original analysis, opinion, or context beyond the source?
3. has_why_it_matters: Is there a clear "why this matters" section that connects to the audience?
4. source_similarity_concern: Does the script sound like it copied wording from the source article?
5. hook_strength (0-100): How attention-grabbing is the opening line?
6. claim_exaggeration_risk: Are there exaggerated or unverifiable claims?
7. title_is_misleading: Would the title mislead viewers about the content?
8. sources_present: Are news sources credited in the script?
9. story_is_recent: Based on context, does this seem like a current story?
10. feels_like_ai_slop: Does this feel like generic, low-quality AI-generated content?

Give an overall quality score (0-100):
- 90-100: Excellent, ready to publish
- 70-89: Good, minor improvements possible
- 50-69: Needs revision before production
- Below 50: Reject entirely

verdict should be: "approved", "rejected", or "needs_revision"

Be strict but fair. The goal is to prevent low-quality content from reaching the channel."""


class QualityGate:
    """Multi-check quality gate for scripts."""

    def __init__(self, client: OpenAI, config: dict):
        self.client = client
        self.config = config
        self.min_score = config.get("min_quality_score", 60)
        self.strictness = config.get("strictness", "medium")
        self.model = config.get("llm_model", "gpt-4o")

    def check_script(
        self,
        script: GeneratedScript,
        scored_story: ScoredStory,
    ) -> QualityReport:
        """
        Run all quality checks on a script.

        Returns:
            QualityReport with verdict, scores, and suggestions.
        """
        checks: list[QualityCheck] = []
        warnings: list[str] = []
        suggested_fixes: list[str] = []

        # ---- Local checks (fast, no API) ----

        # Word count check
        wc_check = self._check_word_count(script)
        checks.append(wc_check)
        if not wc_check.passed:
            suggested_fixes.append(wc_check.suggestion or "Adjust word count")

        # Source presence check
        src_check = self._check_sources_present(script)
        checks.append(src_check)
        if not src_check.passed:
            suggested_fixes.append("Add source attribution to the script")

        # Caption line check
        cap_check = self._check_caption_lines(script)
        checks.append(cap_check)
        if not cap_check.passed:
            warnings.append(cap_check.reason)

        # ---- LLM quality check (comprehensive) ----
        try:
            llm_report = self._llm_quality_check(script, scored_story)
            llm_checks, llm_warnings, llm_fixes = self._process_llm_report(llm_report)
            checks.extend(llm_checks)
            warnings.extend(llm_warnings)
            suggested_fixes.extend(llm_fixes)
            llm_score = llm_report.overall_score
        except Exception as e:
            logger.error(f"LLM quality check failed: {e}")
            llm_score = 50
            warnings.append(f"LLM quality check failed: {e}")

        # ---- Compute overall score ----
        check_scores = [c.score for c in checks if c.score > 0]
        avg_check_score = sum(check_scores) / len(check_scores) if check_scores else 50

        # Weight: 60% LLM assessment, 40% local checks
        overall_score = round(0.6 * llm_score + 0.4 * avg_check_score)

        # ---- Determine verdict ----
        failed_critical = sum(1 for c in checks if not c.passed and c.name in {
            "original_commentary", "why_it_matters", "not_ai_slop", "not_just_summary"
        })

        if overall_score < 40 or failed_critical >= 2:
            verdict = QualityVerdict.REJECTED
        elif overall_score < self.min_score or failed_critical >= 1:
            verdict = QualityVerdict.NEEDS_REVISION
        else:
            verdict = QualityVerdict.APPROVED

        # Adjust for strictness
        if self.strictness == "high" and overall_score < 75:
            verdict = QualityVerdict.NEEDS_REVISION
        elif self.strictness == "low" and overall_score >= 45:
            if verdict == QualityVerdict.REJECTED:
                verdict = QualityVerdict.NEEDS_REVISION

        return QualityReport(
            verdict=verdict,
            overall_score=overall_score,
            checks=checks,
            warnings=warnings,
            suggested_fixes=suggested_fixes,
            safe_to_post=verdict == QualityVerdict.APPROVED and not warnings,
        )

    def _check_word_count(self, script: GeneratedScript) -> QualityCheck:
        """Check if word count is within target range."""
        wc = script.word_count
        min_wc = self.config.get("target_word_count_min", 80)
        max_wc = self.config.get("target_word_count_max", 120)

        if min_wc <= wc <= max_wc:
            return QualityCheck(
                name="word_count",
                passed=True,
                score=90,
                reason=f"Word count {wc} is within range ({min_wc}-{max_wc})",
            )
        elif wc < min_wc:
            return QualityCheck(
                name="word_count",
                passed=False,
                score=40,
                reason=f"Script too short: {wc} words (minimum: {min_wc})",
                suggestion=f"Add more detail or context to reach at least {min_wc} words",
            )
        else:
            return QualityCheck(
                name="word_count",
                passed=False,
                score=50,
                reason=f"Script too long: {wc} words (maximum: {max_wc})",
                suggestion=f"Trim to under {max_wc} words for a tight short-form video",
            )

    def _check_sources_present(self, script: GeneratedScript) -> QualityCheck:
        """Check if sources are credited in the script."""
        if script.source_list and len(script.source_list) > 0:
            return QualityCheck(
                name="sources_present",
                passed=True,
                score=90,
                reason=f"Sources credited: {', '.join(script.source_list[:3])}",
            )
        return QualityCheck(
            name="sources_present",
            passed=False,
            score=20,
            reason="No sources credited in the script",
            suggestion="Add source attribution (e.g., 'according to TechCrunch')",
        )

    def _check_caption_lines(self, script: GeneratedScript) -> QualityCheck:
        """Check if caption lines are properly formatted."""
        if not script.caption_lines:
            return QualityCheck(
                name="caption_lines",
                passed=False,
                score=30,
                reason="No caption lines generated",
                suggestion="Generate caption lines (3-5 words each)",
            )

        long_lines = [l for l in script.caption_lines if len(l.split()) > 7]
        if long_lines:
            return QualityCheck(
                name="caption_lines",
                passed=True,  # Warning, not failure
                score=60,
                reason=f"{len(long_lines)} caption lines are too long for mobile",
                suggestion="Keep caption lines to 3-5 words for readability",
            )

        return QualityCheck(
            name="caption_lines",
            passed=True,
            score=90,
            reason=f"{len(script.caption_lines)} caption lines, well-formatted",
        )

    def _llm_quality_check(
        self,
        script: GeneratedScript,
        scored_story: ScoredStory,
    ) -> LLMQualityCheck:
        """Run comprehensive LLM-based quality assessment."""
        user_prompt = f"""Evaluate this script for quality:

STORY:
Title: {scored_story.story.title}
Source: {scored_story.story.source_name}
Original snippet: {scored_story.story.snippet[:200]}

SCRIPT:
{script.full_script}

SCRIPT METADATA:
- Structure used: {script.structure_type.value}
- Word count: {script.word_count}
- Title ideas: {', '.join(script.title_ideas[:3])}
- Sources credited: {', '.join(script.source_list)}
- Commentary notes: {script.commentary_notes}

Evaluate thoroughly against all quality criteria."""

        completion = self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": QUALITY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format=LLMQualityCheck,
            temperature=0.2,
        )

        result = completion.choices[0].message.parsed
        if result is None:
            raise ValueError("LLM refused quality check")
        return result

    def _process_llm_report(
        self, report: LLMQualityCheck
    ) -> tuple[list[QualityCheck], list[str], list[str]]:
        """Process LLM quality report into structured checks."""
        checks = []
        warnings = []
        fixes = []

        # Summary check
        checks.append(QualityCheck(
            name="not_just_summary",
            passed=not report.is_just_summary,
            score=20 if report.is_just_summary else 90,
            reason="Script is just a summary" if report.is_just_summary else "Script adds original value",
            suggestion="Add original commentary and analysis" if report.is_just_summary else None,
        ))

        # Commentary check
        checks.append(QualityCheck(
            name="original_commentary",
            passed=report.has_original_commentary,
            score=90 if report.has_original_commentary else 20,
            reason="Has original commentary" if report.has_original_commentary else "Missing original commentary",
            suggestion=None if report.has_original_commentary else "Add unique analysis or perspective",
        ))

        # Why it matters
        checks.append(QualityCheck(
            name="why_it_matters",
            passed=report.has_why_it_matters,
            score=90 if report.has_why_it_matters else 25,
            reason="Has 'why it matters' section" if report.has_why_it_matters else "Missing 'why it matters'",
            suggestion=None if report.has_why_it_matters else "Explain why students/devs should care",
        ))

        # Hook strength
        checks.append(QualityCheck(
            name="hook_strength",
            passed=report.hook_strength >= self.config.get("min_hook_strength", 50),
            score=report.hook_strength,
            reason=f"Hook strength: {report.hook_strength}/100",
            suggestion="Write a more attention-grabbing opening" if report.hook_strength < 50 else None,
        ))

        # AI slop check
        checks.append(QualityCheck(
            name="not_ai_slop",
            passed=not report.feels_like_ai_slop,
            score=10 if report.feels_like_ai_slop else 90,
            reason="Feels like generic AI content" if report.feels_like_ai_slop else "Feels authentic and original",
            suggestion="Rewrite with more personality and specificity" if report.feels_like_ai_slop else None,
        ))

        # Source similarity
        if report.source_similarity_concern:
            warnings.append("Script wording may be too close to the source article")
            fixes.append("Rephrase to use original wording")

        # Exaggeration
        if report.claim_exaggeration_risk:
            warnings.append("Some claims may be exaggerated or unverifiable")
            fixes.append("Tone down claims or add hedging language")

        # Misleading title
        if report.title_is_misleading:
            warnings.append("Title may be misleading")
            fixes.append("Revise title to accurately reflect content")

        # Add LLM's own warnings and fixes
        warnings.extend(report.warnings)
        fixes.extend(report.suggested_fixes)

        return checks, warnings, fixes
