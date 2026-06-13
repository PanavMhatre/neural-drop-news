"""
Metadata generator using GPT-4o Structured Outputs.

Generates titles, descriptions, hashtags, and platform recommendations
for each video package.
"""

import logging
from typing import Optional

from openai import OpenAI

from src.models.schemas import (
    GeneratedScript,
    LLMMetadataOutput,
    ScoredStory,
    VideoMetadata,
    VoiceConfig,
)

logger = logging.getLogger(__name__)

METADATA_SYSTEM_PROMPT = """You are a social media strategist for a YouTube Shorts channel about AI and tech news.

Generate metadata for a short-form video. The channel targets students, developers, and people interested in AI/tech.

Title rules:
- Generate 3-5 title options
- Curiosity-driven but NOT fake/clickbait
- NOT misleading about the content
- Mention the main company/person/product when relevant
- Keep titles under 60 characters
- Do NOT use all caps
- Do NOT use excessive punctuation (!!!, ???)

Description rules:
- Summarize the story in 1-2 sentences
- Include source attribution
- Include AI disclosure notice
- MUST end with: "\n\n🧠 Get the 3-minute AI briefing → bit.ly/neural-drop"
- Keep it concise
- Do NOT say "newsletter" — say "briefing", "AI drops", or "cheat sheet"

Hashtag rules:
- 8-12 relevant hashtags
- MUST include: #NeuralDrop #AIBriefing #AIDrops
- Include channel hashtags: #AINews #TechShorts #TechNews
- Include topic-specific tags
- Do NOT use spammy/irrelevant tags
- Mix popular and niche tags

Platform recommendation:
- YouTube Shorts, TikTok, or Instagram Reels
- Consider story type and audience

Caption text rules:
- Every video caption MUST end with: "Full AI briefing in bio → Neural Drop"
- Do NOT say "subscribe to my newsletter"

Flag manual review if:
- Story involves sensitive topics (layoffs, legal issues)
- Claims are difficult to verify
- Story involves speculation
- Content could be controversial"""


class MetadataGenerator:
    """Generates video metadata using GPT-4o."""

    def __init__(self, client: OpenAI, config: dict):
        self.client = client
        self.config = config
        self.model = config.get("llm_model", "gpt-4o")

    def generate_metadata(
        self,
        script: GeneratedScript,
        scored_story: ScoredStory,
        voice_config: VoiceConfig,
    ) -> VideoMetadata:
        """
        Generate complete metadata for a video package.

        Args:
            script: The generated script.
            scored_story: The scored story.
            voice_config: Voice configuration used.

        Returns:
            VideoMetadata with titles, description, hashtags, etc.
        """
        story = scored_story.story

        user_prompt = f"""Generate metadata for this video:

Story title: {story.title}
Source: {story.source_name}
Category: {scored_story.detected_category.value}

Script:
{script.full_script[:300]}

Title ideas from script generation: {', '.join(script.title_ideas)}

Generate optimized metadata for this video."""

        try:
            from src.utils.llm import llm_parse
            result = llm_parse(
                self.client,
                self.model,
                [
                    {"role": "system", "content": METADATA_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                LLMMetadataOutput,
                temperature=0.6,
                max_tokens=2000,
            )
        except Exception as e:
            logger.error(f"Metadata generation failed: {e}")
            # Fallback to script-generated metadata
            return self._fallback_metadata(script, scored_story, voice_config)

        # Build AI disclosure
        ai_disclosure = (
            f"This video uses AI-generated narration (OpenAI {voice_config.model}, "
            f"voice: {voice_config.voice}) and AI-assisted script writing and editing. "
            f"All facts are sourced from credited publications. "
            f"Content was reviewed by a human before posting."
        )

        # Build description with disclosure
        description = result.description
        if ai_disclosure not in description:
            description += f"\n\n🤖 AI Disclosure: {ai_disclosure}"

        # Add sources to description
        if script.source_list:
            sources_str = "\n".join(f"• {s}" for s in script.source_list)
            description += f"\n\n📰 Sources:\n{sources_str}"

        # Add Neural Drop CTA to description
        neural_drop_cta = "\n\n🧠 Get the 3-minute AI briefing → bit.ly/neural-drop"
        if "bit.ly/neural-drop" not in description:
            description += neural_drop_cta

        # Ensure Neural Drop hashtags are included
        neural_drop_tags = ["#NeuralDrop", "#AIBriefing", "#AIDrops"]
        merged_hashtags = list(result.hashtags)
        for tag in neural_drop_tags:
            if tag not in merged_hashtags:
                merged_hashtags.append(tag)

        return VideoMetadata(
            title_options=result.title_options[:5],
            description=description,
            hashtags=merged_hashtags,
            source_links=[story.url] + [s for s in script.source_list if s.startswith("http")],
            ai_disclosure=ai_disclosure,
            recommended_platform=result.platform_recommendation,
            review_warnings=result.review_warnings,
            manual_review_required=result.manual_review_required,
        )

    def _fallback_metadata(
        self,
        script: GeneratedScript,
        scored_story: ScoredStory,
        voice_config: VoiceConfig,
    ) -> VideoMetadata:
        """Generate basic metadata when LLM fails."""
        ai_disclosure = (
            f"AI-generated narration ({voice_config.model}, voice: {voice_config.voice}). "
            f"AI-assisted editing. Sources credited. Human reviewed."
        )

        fallback_description = (
            f"{script.description}\n\n🤖 {ai_disclosure}"
            f"\n\n🧠 Get the 3-minute AI briefing → bit.ly/neural-drop"
        )

        fallback_hashtags = script.hashtags or ["#AINews", "#TechShorts", "#TechNews"]
        for tag in ["#NeuralDrop", "#AIBriefing", "#AIDrops"]:
            if tag not in fallback_hashtags:
                fallback_hashtags.append(tag)

        return VideoMetadata(
            title_options=script.title_ideas[:5] or [scored_story.story.title[:60]],
            description=fallback_description,
            hashtags=fallback_hashtags,
            source_links=[scored_story.story.url],
            ai_disclosure=ai_disclosure,
            recommended_platform="YouTube Shorts",
            review_warnings=["Metadata generated with fallback — review carefully"],
            manual_review_required=True,
        )
