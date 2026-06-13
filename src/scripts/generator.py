"""
Script generator using GPT-4o Structured Outputs.

Creates original, commentary-rich scripts for short-form video content.
Enforces originality, source crediting, and audience relevance.
"""

import logging
from typing import Optional

from openai import OpenAI

from src.utils.llm import llm_parse
from src.models.schemas import (
    GeneratedScript,
    LLMScriptOutput,
    ScoredStory,
    ScriptSection,
    ScriptStructureType,
    VisualCue,
)
from src.scripts.structures import ScriptStructure, get_structure

import re

logger = logging.getLogger(__name__)


def _clean_script(text: str) -> str:
    """Strip stage directions and markdown labels that some models add (e.g. **Visual:** ...)."""
    # Remove **Label:** lines (DeepSeek-style stage directions)
    text = re.sub(r'^\*\*[^*]+\*\*:.*$', '', text, flags=re.MULTILINE)
    # Remove [bracketed directions]
    text = re.sub(r'\[.*?\]', '', text)
    # Collapse multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

SCRIPT_SYSTEM_PROMPT = """You are a scriptwriter for a YouTube Shorts channel called "{channel_name}".
Channel angle: Fast AI and tech news explained for students, developers, and people trying to understand where tech money/opportunity is moving.

Target audience: College students, CS students, young software engineers, people interested in AI, startups, and tech business.

You write SHORT scripts (25-45 seconds, 80-120 words) that are:
- Original commentary, NOT just reading news articles
- Educational — viewers learn something useful
- Relevant — explains why students/developers should care
- Grounded — uses sources for facts, never makes stuff up
- Punchy — every sentence earns its place
- Varied — uses different hooks, structures, and phrasing

CRITICAL RULES:
1. Do NOT copy article wording. Rewrite everything in your own voice.
2. Do NOT make up facts. If unsure, say "reportedly" or "according to [source]".
3. Do NOT give financial, legal, or medical advice.
4. Every script MUST have a "why this matters" section with original analysis.
5. Keep it conversational — you're talking to a friend who's into tech.
6. Credit sources naturally (e.g., "according to TechCrunch" or "Bloomberg reports").
7. The hook must grab attention in the first 2 seconds.
8. End with a punchy takeaway that naturally references the daily AI briefing.

DISTRIBUTION / NEURAL DROP RULES:
9. The closing line MUST naturally reference "the daily AI briefing", "Neural Drop", "the full breakdown", or "the top 5 AI moves" — pick one that fits the story.
10. Do NOT say "newsletter" — instead say "briefing", "cheat sheet", "top 5 AI stories", "AI drops", or "the full breakdown".
11. Closing line examples that work well:
    - "I break down the top AI moves daily — link in bio."
    - "Full breakdown on Neural Drop."
    - "I track every major AI drop — the daily briefing has more."
    - "If you're trying to stay ahead of AI, I got you — link in bio."
12. Keep the CTA natural and short — do NOT make it sound like a hard sell or ad read.

{structure_instruction}

RECENTLY USED HOOKS (avoid similar phrasing):
{recent_hooks}

Caption lines should be 3-5 words each, readable on a phone screen.

Visual plan should describe what text/graphics to show during each section."""


class ScriptGenerator:
    """Generates original scripts using GPT-4o."""

    def __init__(self, client: OpenAI, config: dict):
        self.client = client
        self.config = config
        self.channel_name = config.get("channel_name", "TechPulse Shorts")
        self.model = config.get("llm_model", "gpt-4o")
        self.temperature = config.get("llm_temperature", 0.8)
        self.target_words = (
            config.get("target_word_count_min", 80),
            config.get("target_word_count_max", 120),
        )

    def generate_script(
        self,
        scored_story: ScoredStory,
        structure: ScriptStructure,
        recent_hooks: list[str],
    ) -> GeneratedScript:
        """
        Generate an original script for a scored story.

        Args:
            scored_story: The story to script.
            structure: The script structure template to use.
            recent_hooks: Recently used hook phrases (for variation).

        Returns:
            A complete GeneratedScript.
        """
        story = scored_story.story

        # Build system prompt
        hooks_str = "\n".join(f"- {h}" for h in recent_hooks[:10]) if recent_hooks else "None yet"
        system_prompt = SCRIPT_SYSTEM_PROMPT.format(
            channel_name=self.channel_name,
            structure_instruction=structure.system_instruction,
            recent_hooks=hooks_str,
        )

        # Build user prompt
        user_prompt = f"""Write a script for this story:

Title: {story.title}
Source: {story.source_name}
Published: {story.published_at.isoformat() if story.published_at else 'Recent'}
Summary: {story.snippet[:400]}
URL: {story.url}
Category: {scored_story.detected_category.value}
Tone: {scored_story.detected_tone.value}
Score: {scored_story.score.total_score}/100

Structure to use: {structure.name}
Example hook style: {structure.example_hook}

Requirements:
- Target length: {self.target_words[0]}-{self.target_words[1]} words
- Duration: 25-45 seconds when read aloud
- Must include original commentary (not just summarizing)
- Must explain why students/devs should care
- Must credit the source naturally
- Must NOT copy article wording
- Caption lines should be 3-5 words each

Generate the complete script with all required fields."""

        try:
            result = llm_parse(
                self.client,
                self.model,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                LLMScriptOutput,
                temperature=self.temperature,
            )
        except Exception as e:
            logger.error(f"Script generation failed: {e}")
            raise

        # Convert LLM output to our internal model
        return self._convert_output(result, structure.type)

    def _convert_output(
        self, llm_output: LLMScriptOutput, structure_type: ScriptStructureType
    ) -> GeneratedScript:
        """Convert LLM output to GeneratedScript model."""
        sections = ScriptSection(
            hook=llm_output.hook,
            main_explanation=llm_output.main_explanation,
            why_it_matters=llm_output.why_it_matters,
            student_dev_angle=llm_output.student_dev_angle,
            closing_line=llm_output.closing_line,
        )

        visual_plan = []
        for vp in llm_output.visual_plan:
            visual_plan.append(VisualCue(
                section=vp.section,
                description=vp.description,
                text_overlay=vp.text_overlay,
                duration_hint=vp.duration_hint,
            ))

        return GeneratedScript(
            sections=sections,
            full_script=_clean_script(llm_output.full_script),
            word_count=llm_output.word_count,
            estimated_duration_seconds=llm_output.estimated_duration_seconds,
            structure_type=structure_type,
            visual_plan=visual_plan,
            caption_lines=llm_output.caption_lines,
            title_ideas=llm_output.title_ideas[:5],
            description=llm_output.description,
            hashtags=llm_output.hashtags,
            source_list=llm_output.source_list,
            commentary_notes=llm_output.commentary_notes,
        )

    def regenerate_with_feedback(
        self,
        scored_story: ScoredStory,
        structure: ScriptStructure,
        previous_script: GeneratedScript,
        feedback: list[str],
        recent_hooks: list[str],
    ) -> GeneratedScript:
        """
        Regenerate a script incorporating quality feedback.

        Args:
            scored_story: The story.
            structure: The script structure.
            previous_script: The script that failed quality checks.
            feedback: List of issues to fix.
            recent_hooks: Recently used hooks.

        Returns:
            A revised GeneratedScript.
        """
        story = scored_story.story
        hooks_str = "\n".join(f"- {h}" for h in recent_hooks[:10]) if recent_hooks else "None yet"

        system_prompt = SCRIPT_SYSTEM_PROMPT.format(
            channel_name=self.channel_name,
            structure_instruction=structure.system_instruction,
            recent_hooks=hooks_str,
        )

        feedback_str = "\n".join(f"- {f}" for f in feedback)

        user_prompt = f"""REVISION REQUEST: The previous script had quality issues. Fix them.

Story: {story.title}
Source: {story.source_name}
Summary: {story.snippet[:300]}

Previous script:
{previous_script.full_script}

ISSUES TO FIX:
{feedback_str}

Rewrite the script to address ALL issues while keeping the same structure ({structure.name}).
Make it better, more original, and more engaging."""

        try:
            result = llm_parse(
                self.client,
                self.model,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                LLMScriptOutput,
                temperature=self.temperature + 0.1,
            )
        except Exception as e:
            logger.error(f"Script revision failed: {e}")
            raise

        return self._convert_output(result, structure.type)
