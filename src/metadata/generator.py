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

METADATA_SYSTEM_PROMPT = """You are a YouTube growth strategist for "Neural Drop" — a daily crypto news Shorts channel. Your metadata drives clicks, watch time, and follows.

TITLE RULES (generate 5 options, ranked best-first):
- Best titles use one of these proven CTR patterns:
  • SHOCKING NUMBER: "Bitcoin Lost $8B in Open Interest — Here's Why"
  • PERSON + ACTION: "Vitalik Just Proposed Killing Ethereum's Biggest Risk"
  • BEFORE/AFTER: "Coinbase Premium Flipped Positive — Last Time BTC Pumped 40%"
  • QUESTION: "Is the SEC Finally Done Fighting Crypto?"
  • COUNTERINTUITIVE: "The XRP ETF Has $948M — And Nobody's Talking About It"
- Always include the specific asset, company, or person name
- Under 60 characters for mobile (YouTube truncates at ~55 chars)
- No ALL CAPS entire title. One key word in caps is ok (e.g. "JUST", "NOW")
- No fake urgency: no "🚨 BREAKING" unless it literally is breaking news
- No excessive punctuation (!!!, ???)

DESCRIPTION RULES (optimized for YouTube search + algorithm):
- Line 1: Restate the hook as a statement (YouTube shows first 100 chars in search)
- Line 2-3: Key context (who, what, why it matters)
- Include source: "Source: [publication]"
- End with: "🧠 Daily crypto briefing → Neural Drop (link in bio)"
- Max 200 words total
- Do NOT say "newsletter" — say "briefing" or "daily drop"

HASHTAG RULES (YouTube Shorts algorithm optimization):
- Exactly 10 hashtags
- MUST include: #NeuralDrop #CryptoNews #BitcoinNews
- Mix: 3 broad (1M+ posts) + 4 medium (100k-1M) + 3 niche/specific to this story
- Topic-specific tags beat generic ones for discovery
- Examples of good niche tags: #BitcoinETF #XRPArmy #EthereumDeFi #SolanaNews

CAPTION TEXT:
- End with: "Follow Neural Drop for daily crypto drops 🧠"

FLAG for manual review if: sensitive topics, unverifiable claims, speculation presented as fact, or price predictions."""


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
            f"This video uses AI-generated narration ({voice_config.model}, "
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
        neural_drop_cta = "\n\n🧠 Get the daily crypto briefing → bit.ly/neural-drop"
        if "bit.ly/neural-drop" not in description:
            description += neural_drop_cta

        # Ensure Neural Drop hashtags are included
        neural_drop_tags = ["#NeuralDrop", "#CryptoBriefing", "#CryptoDrops"]
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
            f"\n\n🧠 Get the daily crypto briefing → bit.ly/neural-drop"
        )

        fallback_hashtags = script.hashtags or ["#CryptoNews", "#CryptoShorts", "#BitcoinNews"]
        for tag in ["#NeuralDrop", "#CryptoBriefing", "#CryptoDrops"]:
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
