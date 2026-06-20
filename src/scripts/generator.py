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

SCRIPT_SYSTEM_PROMPT = """You are the head scriptwriter for "{channel_name}" — a daily crypto news YouTube Shorts channel optimizing for maximum watch time, shares, and follows.

TARGET AUDIENCE: Crypto traders, DeFi users, developers, and curious newcomers aged 18-30. They scroll fast, skip slow, and share only what surprises them.

════ HOOK — THE ONLY THING THAT MATTERS IN THE FIRST 2 SECONDS ════
- ONE sentence. Under 12 words. Must name a specific thing: company, person, dollar amount, event.
- Pattern options that retain viewers:
  • SHOCK NUMBER: "Bitcoin just lost $8B in open interest in 24 hours."
  • NAME DROP + TWIST: "Vitalik just proposed killing Ethereum's biggest risk."
  • COUNTERINTUITIVE: "The SEC approved it. Crypto ETF assets just crossed $1B."
  • DEADLINE/URGENCY: "Coinbase Premium went positive — last time this happened, BTC pumped 40%."
- NEVER start with: "So", "Well", "Here's the thing", "You might have heard", "Recently"

RETENTION TECHNIQUES (use at least one per script):
- Open loop: hint at the payoff without giving it away in the hook
- Pattern interrupt: unexpected pivot after the hook ("But here's what nobody's saying...")
- Specificity creates credibility: "$63,241" beats "over $63k"
- End on a question or unresolved tension to drive comments

SCRIPT RULES:
1. 80-120 words total. Every word must earn its place. Cut filler ruthlessly.
2. Specific names, dollar amounts, dates — zero vague references.
3. One original insight the viewer won't find just by reading the headline.
4. No financial advice. Facts + analysis only.
5. Source in one natural phrase: "per CoinDesk", "Bloomberg reports", "per the SEC filing".
6. CTA must be conversational and specific:
   - "I cover this daily — follow Neural Drop."
   - "Full breakdown in the bio."
   - "Drop a comment: bullish or bearish?"
7. Never say "newsletter". Say "daily drop", "briefing", or "breakdown".

{structure_instruction}

RECENTLY USED HOOKS (DO NOT reuse similar phrasing or structure):
{recent_hooks}

Caption lines: 3-5 words, punchy, phone-readable at a glance.
Visual plan: one concrete, specific visual per section — price chart with numbers, logo, headline screenshot, person's face. NO generic "crypto background" descriptions."""


def _build_glm_client() -> Optional[OpenAI]:
    """GLM-5.1 is now primary (passed as self.client). No second model needed."""
    return None


def _judge_scripts(script_a: str, script_b: str, label_a: str, label_b: str) -> tuple[str, str]:
    """Groq gpt-oss-120b judges two scripts and returns (winning_script, winner_label)."""
    import os
    groq_key = (
        os.getenv("GROQ_API_KEY_1") or os.getenv("GROQ_API_KEY_2")
        or os.getenv("GROQ_API_KEY_3") or os.getenv("GROQ_API_KEY")
    )
    if not groq_key:
        return script_a, label_a  # no judge, default to primary
    judge = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
    try:
        r = judge.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": f"""You are a script quality judge for a crypto YouTube Shorts channel.
Pick the better script based on: hook strength, originality, punchiness, clarity, closing line memorability.

SCRIPT A:
{script_a}

SCRIPT B:
{script_b}

Respond with exactly one letter: A or B"""}],
            temperature=0.1,
            max_tokens=5,
        )
        winner = r.choices[0].message.content.strip().upper()
        if "B" in winner:
            logger.info(f"Judge picked {label_b} over {label_a}")
            return script_b, label_b
        logger.info(f"Judge picked {label_a} over {label_b}")
        return script_a, label_a
    except Exception as e:
        logger.warning(f"Judge failed ({e}), using primary script")
        return script_a, label_a


class ScriptGenerator:
    """Generates scripts using dual-model comparison: DeepSeek v4 Flash vs GLM-5.1, judge picks best."""

    def __init__(self, client: OpenAI, config: dict, fallback_client=None):
        self.client = client
        self.fallback_client = fallback_client  # Groq — used when all NVIDIA keys are exhausted
        self.config = config
        self.channel_name = config.get("channel_name", "TechPulse Shorts")
        self.model = config.get("llm_model", "z-ai/glm-5.1")
        self.fallback_model = "openai/gpt-oss-120b"
        self.temperature = config.get("llm_temperature", 0.8)
        self.target_words = (
            config.get("target_word_count_min", 80),
            config.get("target_word_count_max", 120),
        )
        # Second model for comparison
        self._glm_client = _build_glm_client()
        self._glm_model = "z-ai/glm-5.1"
        if self._glm_client:
            logger.info("Dual-model script comparison enabled: DeepSeek v4 Flash vs GLM-5.1")

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

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        if self._glm_client:
            # Generate both in parallel, judge picks the better full_script
            from concurrent.futures import ThreadPoolExecutor

            def _gen_primary():
                return llm_parse(self.client, self.model, messages, LLMScriptOutput, self.temperature)

            def _gen_glm():
                return llm_parse(self._glm_client, self._glm_model, messages, LLMScriptOutput, self.temperature)

            with ThreadPoolExecutor(max_workers=2) as pool:
                f_primary = pool.submit(_gen_primary)
                f_glm = pool.submit(_gen_glm)
                primary_result = exc_primary = None
                glm_result = exc_glm = None
                try:
                    primary_result = f_primary.result()
                except Exception as e:
                    exc_primary = e
                try:
                    glm_result = f_glm.result()
                except Exception as e:
                    exc_glm = e

            if primary_result and glm_result:
                winning_script, winner = _judge_scripts(
                    primary_result.full_script, glm_result.full_script,
                    "DeepSeek", "GLM-5.1"
                )
                result = primary_result if winner == "DeepSeek" else glm_result
                result.full_script = winning_script
            elif primary_result:
                if exc_glm:
                    logger.warning(f"GLM-5.1 failed, using DeepSeek: {exc_glm}")
                result = primary_result
            elif glm_result:
                logger.warning(f"DeepSeek failed, using GLM-5.1: {exc_primary}")
                result = glm_result
            else:
                raise Exception(f"Both models failed — DeepSeek: {exc_primary} | GLM: {exc_glm}")
        else:
            try:
                result = llm_parse(self.client, self.model, messages, LLMScriptOutput, self.temperature)
            except Exception as e:
                if self.fallback_client:
                    logger.warning(f"Primary LLM failed ({e}) — falling back to Groq")
                    result = llm_parse(self.fallback_client, self.fallback_model, messages, LLMScriptOutput, self.temperature)
                else:
                    logger.error(f"Script generation failed: {e}")
                    raise

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
