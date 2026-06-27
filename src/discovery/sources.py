"""
Source credibility registry.

Assigns trust tiers to news sources for scoring. Tier 1 sources are
major publications with editorial standards. Tier 3 sources are blogs
and lesser-known outlets that need extra scrutiny.
"""

from enum import IntEnum
from typing import Optional


class SourceTier(IntEnum):
    """Source credibility tiers."""
    TIER_1 = 1   # Major publications with strong editorial standards
    TIER_2 = 2   # Established tech publications
    TIER_3 = 3   # Blogs, smaller outlets, aggregators
    UNKNOWN = 4  # Not in registry


# Credibility scores by tier
TIER_SCORES = {
    SourceTier.TIER_1: 90,
    SourceTier.TIER_2: 75,
    SourceTier.TIER_3: 50,
    SourceTier.UNKNOWN: 35,
}

# Source registry — lowercase domain fragments → tier
SOURCE_REGISTRY: dict[str, SourceTier] = {
    # Tier 1: Major outlets with editorial standards
    "reuters": SourceTier.TIER_1,
    "bloomberg": SourceTier.TIER_1,
    "nytimes": SourceTier.TIER_1,
    "wsj": SourceTier.TIER_1,
    "washingtonpost": SourceTier.TIER_1,
    "bbc": SourceTier.TIER_1,
    "cnbc": SourceTier.TIER_1,
    "ft.com": SourceTier.TIER_1,
    "apnews": SourceTier.TIER_1,
    "theguardian": SourceTier.TIER_1,
    "nature.com": SourceTier.TIER_1,
    "science.org": SourceTier.TIER_1,
    "ieee": SourceTier.TIER_1,
    "arxiv": SourceTier.TIER_1,

    # Tier 1: Crypto-native outlets with strong editorial standards
    "coindesk": SourceTier.TIER_1,
    "cointelegraph": SourceTier.TIER_1,

    # Tier 2: Established tech publications
    "techcrunch": SourceTier.TIER_2,
    "theverge": SourceTier.TIER_2,
    "wired": SourceTier.TIER_2,
    "arstechnica": SourceTier.TIER_2,
    "engadget": SourceTier.TIER_2,
    "thenextweb": SourceTier.TIER_2,
    "venturebeat": SourceTier.TIER_2,
    "zdnet": SourceTier.TIER_2,
    "cnet": SourceTier.TIER_2,
    "theinformation": SourceTier.TIER_2,
    "semafor": SourceTier.TIER_2,
    "protocol": SourceTier.TIER_2,
    "9to5mac": SourceTier.TIER_2,
    "9to5google": SourceTier.TIER_2,
    "macrumors": SourceTier.TIER_2,
    "tomshardware": SourceTier.TIER_2,
    "anandtech": SourceTier.TIER_2,
    "businessinsider": SourceTier.TIER_2,
    "forbes": SourceTier.TIER_2,
    "fortune": SourceTier.TIER_2,
    "mit technology review": SourceTier.TIER_2,
    "technologyreview": SourceTier.TIER_2,
    "hacker news": SourceTier.TIER_2,
    "ycombinator": SourceTier.TIER_2,
    # Established crypto publications
    "decrypt": SourceTier.TIER_2,
    "theblock": SourceTier.TIER_2,
    "blockworks": SourceTier.TIER_2,
    "unchainedcrypto": SourceTier.TIER_2,
    "cryptobriefing": SourceTier.TIER_2,
    "thedefiant": SourceTier.TIER_2,
    "dlnews": SourceTier.TIER_2,
    "bitcoinmagazine": SourceTier.TIER_2,
    "protos": SourceTier.TIER_2,
    "cryptoslate": SourceTier.TIER_2,
    "axios": SourceTier.TIER_2,
    "investing.com": SourceTier.TIER_2,
    "pymnts": SourceTier.TIER_2,

    # Tier 3: Blogs, smaller outlets
    "medium": SourceTier.TIER_3,
    "substack": SourceTier.TIER_3,
    "dev.to": SourceTier.TIER_3,
    "hackernoon": SourceTier.TIER_3,
    "towardsdatascience": SourceTier.TIER_3,
    "analyticsvidhya": SourceTier.TIER_3,
    "techspot": SourceTier.TIER_3,
    "gizmodo": SourceTier.TIER_3,
    "mashable": SourceTier.TIER_3,
    "digitaltrends": SourceTier.TIER_3,
    "bgr": SourceTier.TIER_3,
    "phonearena": SourceTier.TIER_3,
    # Smaller crypto outlets
    "coingape": SourceTier.TIER_3,
    "newsbtc": SourceTier.TIER_3,
    "bitcoinist": SourceTier.TIER_3,
    "cryptopotato": SourceTier.TIER_3,
    "ambcrypto": SourceTier.TIER_3,
    "u.today": SourceTier.TIER_3,
    "finbold": SourceTier.TIER_3,
    "beincrypto": SourceTier.TIER_3,
    "cryptonews": SourceTier.TIER_3,
    "coinpedia": SourceTier.TIER_3,
    "cryptotimes": SourceTier.TIER_3,
}


def get_source_tier(source_name: str, source_url: Optional[str] = None) -> SourceTier:
    """
    Look up the credibility tier for a source.

    Checks both source name and URL against the registry.
    """
    search_strings = [source_name.lower()]
    if source_url:
        search_strings.append(source_url.lower())

    for search in search_strings:
        for key, tier in SOURCE_REGISTRY.items():
            if key in search:
                return tier

    return SourceTier.UNKNOWN


def get_credibility_score(source_name: str, source_url: Optional[str] = None) -> int:
    """Get the numeric credibility score for a source (0-100)."""
    tier = get_source_tier(source_name, source_url)
    return TIER_SCORES[tier]
