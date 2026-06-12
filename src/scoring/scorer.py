"""
Story scorer using GPT-4o Structured Outputs.

Evaluates each discovered story on 8 categories and makes
an accept/reject decision based on configurable thresholds.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from openai import OpenAI
from pydantic import BaseModel

from src.discovery.sources import get_credibility_score, get_source_tier
from src.models.schemas import (
    LLMStoryScore,
    RawStory,
    ScoredStory,
    StoryCategory,
    StoryScore,
    StoryTone,
)

logger = logging.getLogger(__name__)

SCORING_SYSTEM_PROMPT = """You are a content strategist for Neural Drop, a YouTube Shorts channel covering daily crypto and digital-asset news.
Your audience is crypto traders, builders, DeFi users, and curious newcomers who want to understand price moves, regulation, and institutional adoption.

Your job is to evaluate whether a news story is worth making into a short video.

Score each category from 0 to 100:
- freshness: How recent and timely is this story? (100 = breaking today, 50 = couple days old, 0 = weeks old)
- source_credibility: How trustworthy is the source? Reuters/Bloomberg/CoinDesk/Decrypt = high, random blogs = low
- relevance: How relevant is this to crypto markets, regulation, ETFs, DeFi, exchanges, stablecoins, or institutional adoption? (100 = core crypto story, 0 = unrelated)
- viral_potential: How likely is the audience to share/engage? (100 = everyone will talk about it, 0 = boring)
- educational_value: How much will viewers learn about crypto? (100 = teaches something important, 0 = no learning value)
- business_angle: Does this reveal price impact, policy impact, treasury move, or on-chain risk? (100 = major insight, 0 = no business angle)
- visual_potential: How well can this be visualized in a short video? (100 = has real footage/charts/events, 0 = nothing to show)
- explainability: Can this be clearly explained in under 45 seconds? (100 = simple and clear, 0 = too complex)

ACCEPT stories about: Bitcoin, Ethereum, Solana, stablecoins, crypto regulation, ETFs, crypto exchanges, DeFi, mining, institutional adoption, hacks/exploits, treasury moves, on-chain data milestones.

REJECT if:
- The story has no clear crypto or digital-asset angle
- It is purely a traditional finance/stock market story with no crypto relevance
- It is mostly speculation or rumors without credible sourcing
- It cannot be explained simply in under 45 seconds
- It is primarily celebrity gossip, horoscopes, or unrelated lifestyle content

Detected category should be one of: openai, anthropic, google_ai, meta_ai, apple_ai, nvidia, ai_chips, ai_startups, ai_funding, developer_tools, coding_agents, software_engineering, ai_regulation, product_launch, tech_jobs, ai_tools, general_ai, general_tech

Detected tone should be one of: startup_funding, developer_tools, ai_safety, product_launch, layoffs_hiring, general

Map crypto stories to the closest matching category/tone (e.g. Bitcoin ETF → ai_regulation, exchange hack → ai_safety, DeFi protocol launch → product_launch, institutional adoption → startup_funding)."""


def _build_groq_clients() -> list:
    """Build a list of OpenAI-compatible Groq clients from GROQ_API_KEY_1/2/3 or GROQ_API_KEY."""
    import os
    keys = []
    # Support multiple keys for round-robin rotation
    for var in ("GROQ_API_KEY_1", "GROQ_API_KEY_2", "GROQ_API_KEY_3", "GROQ_API_KEY"):
        k = os.getenv(var, "")
        if k and k not in keys:
            keys.append(k)
    return [OpenAI(api_key=k, base_url="https://api.groq.com/openai/v1") for k in keys]


class StoryScorer:
    """Scores stories using Groq (round-robin across keys) with OpenAI fallback."""

    def __init__(self, client: OpenAI, config: dict, analytics_insights: dict | None = None):
        self.client = client
        self.config = config
        self.min_score = config.get("minimum_score", 55)
        self.model = config.get("llm_model", "gpt-4o")

        # Prefer Groq clients for scoring (fast, no rate-limit pain)
        self._groq_clients = _build_groq_clients()
        self._groq_idx = 0
        if self._groq_clients:
            logger.info(f"Groq scoring enabled: {len(self._groq_clients)} key(s) in rotation")

    def _next_scoring_client(self):
        """Return next Groq client in round-robin, or fall back to main client."""
        if self._groq_clients:
            client = self._groq_clients[self._groq_idx % len(self._groq_clients)]
            self._groq_idx += 1
            return client, "llama-3.1-8b-instant"
        return self.client, self.model
        # analytics_insights: output of YouTubeChannelAnalytics.get_performance_insights()
        # Keys used: top_keywords (list of (kw, score)), avg_engagement_30d
        self._top_keywords: dict[str, float] = {}
        if analytics_insights:
            for kw, score in analytics_insights.get("top_keywords", []):
                self._top_keywords[kw.lower()] = float(score)

    def score_story(self, story: RawStory) -> ScoredStory:
        """
        Score a story and decide whether to accept or reject it.

        Combines LLM evaluation with source credibility data.
        """
        # Pre-check: must have crypto/digital-asset angle
        if not self._is_crypto_relevant(story):
            return self._create_rejected(story, "No crypto/digital-asset angle", 0)

        # Pre-check: source credibility
        source_score = get_credibility_score(story.source_name, story.source_url)

        # Pre-check: freshness (reject obviously old stories)
        max_age_hours = self.config.get("freshness_hours", 48)
        freshness_ok, freshness_note = self._check_freshness(story, max_age_hours)

        if not freshness_ok:
            return self._create_rejected(
                story, f"Story too old: {freshness_note}", source_score
            )

        # LLM scoring
        try:
            llm_score = self._llm_score(story, source_score)
        except Exception as e:
            logger.error(f"LLM scoring failed for '{story.title[:60]}': {e}")
            return self._create_rejected(story, f"Scoring failed: {e}", source_score)

        # Build StoryScore
        score = StoryScore(
            freshness=llm_score.freshness,
            source_credibility=max(llm_score.source_credibility, source_score),
            relevance=llm_score.relevance,
            viral_potential=llm_score.viral_potential,
            educational_value=llm_score.educational_value,
            business_angle=llm_score.business_angle,
            visual_potential=llm_score.visual_potential,
            explainability=llm_score.explainability,
        )

        # Analytics boost: if this story's keywords match top-performing channel content,
        # nudge viral_potential and relevance up (max +10 pts each, capped at 100).
        if self._top_keywords:
            title_lower = story.title.lower()
            boost = sum(
                min(1.0, weight / max(self._top_keywords.values()))
                for kw, weight in self._top_keywords.items()
                if kw in title_lower
            )
            boost_pts = min(10, int(boost * 5))
            if boost_pts:
                score.viral_potential = min(100, score.viral_potential + boost_pts)
                score.relevance = min(100, score.relevance + boost_pts)
                logger.info(f"Analytics boost +{boost_pts} for '{story.title[:50]}'")

        # Accept/reject decision
        accepted = llm_score.should_accept and score.total_score >= self.min_score
        rejection_reasons = list(llm_score.rejection_reasons)

        if score.total_score < self.min_score:
            rejection_reasons.append(
                f"Total score {score.total_score} below minimum {self.min_score}"
            )
            accepted = False

        # Map category and tone
        try:
            category = StoryCategory(llm_score.detected_category)
        except ValueError:
            category = StoryCategory.GENERAL_AI

        try:
            tone = StoryTone(llm_score.detected_tone)
        except ValueError:
            tone = StoryTone.GENERAL

        return ScoredStory(
            story=story,
            score=score,
            accepted=accepted,
            rejection_reasons=rejection_reasons,
            detected_category=category,
            detected_tone=tone,
        )

    def score_stories(self, stories: list[RawStory]) -> list[ScoredStory]:
        """Score multiple stories and return sorted by score (descending)."""
        import time
        scored = []
        for story in stories:
            for attempt in range(3):
                try:
                    result = self.score_story(story)
                    scored.append(result)
                    status = "✓" if result.accepted else "✗"
                    logger.info(
                        f"  {status} [{result.score.total_score:3d}] {story.title[:70]}"
                    )
                    break
                except Exception as e:
                    if "429" in str(e) or "rate" in str(e).lower() or "queue" in str(e).lower():
                        wait = 30 * (attempt + 1)
                        logger.warning(f"Rate limited scoring, waiting {wait}s (attempt {attempt+1}/3)")
                        time.sleep(wait)
                    else:
                        logger.error(f"Failed to score story: {e}")
                        break

        # Sort by total score, accepted first
        scored.sort(key=lambda s: (s.accepted, s.score.total_score), reverse=True)
        return scored

    def _llm_score(self, story: RawStory, source_score: int) -> LLMStoryScore:
        """Score a story using Groq (round-robin) or fallback client."""
        user_prompt = f"""Evaluate this news story for our crypto news shorts channel (Neural Drop):

Title: {story.title}
Source: {story.source_name} (pre-scored credibility: {source_score}/100)
Published: {story.published_at.isoformat() if story.published_at else 'Unknown'}
Snippet: {story.snippet[:400]}
URL: {story.url}
Categories detected so far: {', '.join(c.value for c in story.categories)}

Score this story and decide whether it should become a short video."""

        scoring_client, scoring_model = self._next_scoring_client()
        completion = scoring_client.beta.chat.completions.parse(
            model=scoring_model,
            messages=[
                {"role": "system", "content": SCORING_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format=LLMStoryScore,
            temperature=0.3,
        )

        result = completion.choices[0].message.parsed
        if result is None:
            refusal = completion.choices[0].message.refusal
            raise ValueError(f"LLM refused to score: {refusal}")

        return result

    def _is_crypto_relevant(self, story: RawStory) -> bool:
        """Hard pre-filter: reject anything with no crypto/digital-asset angle."""
        CRYPTO_KEYWORDS = {
            "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto",
            "blockchain", "defi", "stablecoin", "usdt", "usdc", "nft",
            "altcoin", "token", "wallet", "exchange", "binance", "coinbase",
            "coindesk", "decrypt", "cointelegraph", "regulation", "sec crypto",
            "digital asset", "web3", "mining", "halving", "etf bitcoin",
            "ethereum etf", "on-chain", "satoshi", "dex", "cefi",
        }
        text = f"{story.title} {story.snippet or ''}".lower()
        return any(kw in text for kw in CRYPTO_KEYWORDS)

    def _check_freshness(
        self, story: RawStory, max_age_hours: int
    ) -> tuple[bool, str]:
        """Check if a story is recent enough."""
        if story.published_at is None:
            return True, "No publish date (will rely on LLM assessment)"

        now = datetime.now(timezone.utc)
        pub = story.published_at
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)

        age_hours = (now - pub).total_seconds() / 3600

        if age_hours > max_age_hours:
            return False, f"{age_hours:.0f} hours old (max: {max_age_hours})"

        return True, f"{age_hours:.0f} hours old"

    def _create_rejected(
        self, story: RawStory, reason: str, source_score: int
    ) -> ScoredStory:
        """Create a rejected ScoredStory with minimal scoring."""
        return ScoredStory(
            story=story,
            score=StoryScore(
                freshness=0,
                source_credibility=source_score,
                relevance=0,
                viral_potential=0,
                educational_value=0,
                business_angle=0,
                visual_potential=0,
                explainability=0,
            ),
            accepted=False,
            rejection_reasons=[reason],
        )
