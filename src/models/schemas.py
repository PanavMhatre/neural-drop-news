"""
Pydantic models for the AI + Tech News Shorts production system.

All structured data flows through these models, ensuring type safety
and validation across the entire pipeline.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class StoryCategory(str, Enum):
    """Categories of stories the system targets."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE_AI = "google_ai"
    META_AI = "meta_ai"
    APPLE_AI = "apple_ai"
    NVIDIA = "nvidia"
    AI_CHIPS = "ai_chips"
    AI_STARTUPS = "ai_startups"
    AI_FUNDING = "ai_funding"
    DEVELOPER_TOOLS = "developer_tools"
    CODING_AGENTS = "coding_agents"
    SOFTWARE_ENGINEERING = "software_engineering"
    AI_REGULATION = "ai_regulation"
    PRODUCT_LAUNCH = "product_launch"
    TECH_JOBS = "tech_jobs"
    AI_TOOLS = "ai_tools"
    GENERAL_AI = "general_ai"
    GENERAL_TECH = "general_tech"


class ScriptStructureType(str, Enum):
    """Script structure templates for variation."""
    SOUNDS_BORING_BUT = "sounds_boring_but"
    EVERYONE_MISSED = "everyone_missed"
    WHAT_ACTUALLY_HAPPENED = "what_actually_happened"
    GOOD_BAD_NEWS = "good_bad_news"
    COMPANY_MOVE = "company_move"
    LEARNING_TO_CODE = "learning_to_code"
    HEADLINE_VS_REALITY = "headline_vs_reality"


class StoryTone(str, Enum):
    """Tone categories affecting voice delivery."""
    STARTUP_FUNDING = "startup_funding"
    DEVELOPER_TOOLS = "developer_tools"
    AI_SAFETY = "ai_safety"
    PRODUCT_LAUNCH = "product_launch"
    LAYOFFS_HIRING = "layoffs_hiring"
    GENERAL = "general"


class QualityVerdict(str, Enum):
    """Quality gate outcome."""
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"


class ReviewStatus(str, Enum):
    """Manual review status."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_EDIT = "needs_edit"


class VisualTemplate(str, Enum):
    """Video visual template types."""
    DARK_GRADIENT = "dark_gradient"
    NEON_CARD = "neon_card"
    SPLIT_SCREEN = "split_screen"
    MINIMAL_CLEAN = "minimal_clean"


# ---------------------------------------------------------------------------
# News Discovery Models
# ---------------------------------------------------------------------------

class RawStory(BaseModel):
    """A news article discovered from a source."""
    title: str = Field(description="Article headline")
    url: str = Field(description="Article URL")
    source_name: str = Field(description="Publisher name (e.g. TechCrunch)")
    source_url: Optional[str] = Field(default=None, description="Publisher domain")
    snippet: str = Field(description="Article excerpt/summary")
    published_at: Optional[datetime] = Field(default=None, description="Publication date")
    image_url: Optional[str] = Field(default=None, description="Article image URL")
    categories: list[StoryCategory] = Field(default_factory=list)
    raw_data: Optional[dict] = Field(default=None, description="Raw API response data")

    @computed_field
    @property
    def url_hash(self) -> str:
        """Deterministic hash of the URL for dedup."""
        return hashlib.sha256(self.url.encode()).hexdigest()[:16]

    @computed_field
    @property
    def title_hash(self) -> str:
        """Hash of normalized title for near-dedup."""
        normalized = self.title.lower().strip()
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Scoring Models
# ---------------------------------------------------------------------------

class StoryScore(BaseModel):
    """Breakdown of how a story scored across categories."""
    freshness: int = Field(ge=0, le=100, description="How recent the story is")
    source_credibility: int = Field(ge=0, le=100, description="Trustworthiness of the source")
    relevance: int = Field(ge=0, le=100, description="Relevance to students/developers")
    viral_potential: int = Field(ge=0, le=100, description="Likelihood of audience engagement")
    educational_value: int = Field(ge=0, le=100, description="How much viewers will learn")
    business_angle: int = Field(ge=0, le=100, description="Business/opportunity insight value")
    visual_potential: int = Field(ge=0, le=100, description="How well this can be visualized")
    explainability: int = Field(ge=0, le=100, description="Can be explained clearly in <45s")

    @computed_field
    @property
    def total_score(self) -> int:
        """Weighted average score."""
        weights = {
            "freshness": 0.15,
            "source_credibility": 0.15,
            "relevance": 0.20,
            "viral_potential": 0.10,
            "educational_value": 0.15,
            "business_angle": 0.10,
            "visual_potential": 0.05,
            "explainability": 0.10,
        }
        total = sum(
            getattr(self, k) * w for k, w in weights.items()
        )
        return round(total)


class ScoredStory(BaseModel):
    """A story with its score and accept/reject decision."""
    story: RawStory
    score: StoryScore
    accepted: bool = Field(description="Whether the story passed scoring thresholds")
    rejection_reasons: list[str] = Field(default_factory=list)
    detected_category: StoryCategory = Field(default=StoryCategory.GENERAL_AI)
    detected_tone: StoryTone = Field(default=StoryTone.GENERAL)


# ---------------------------------------------------------------------------
# Script Models
# ---------------------------------------------------------------------------

class ScriptSection(BaseModel):
    """Individual section of a video script."""
    hook: str = Field(description="Opening hook line (first 2 seconds)")
    main_explanation: str = Field(description="What happened — clear factual explanation")
    why_it_matters: str = Field(description="Why this matters to the audience")
    student_dev_angle: str = Field(description="Specific relevance to students/developers")
    closing_line: str = Field(description="Punchy ending line")


class VisualCue(BaseModel):
    """Visual direction for a section of the video."""
    section: str = Field(description="Which script section this applies to")
    description: str = Field(description="What should be shown visually")
    text_overlay: Optional[str] = Field(default=None, description="Key text to show on screen")
    duration_hint: Optional[float] = Field(default=None, description="Approx duration in seconds")


class GeneratedScript(BaseModel):
    """Complete script output from the LLM."""
    sections: ScriptSection
    hook_card: str = Field(
        default="",
        description="4–6 word visual headline for the on-screen overlay (not the spoken hook)",
    )
    full_script: str = Field(description="Full narration text, ready for TTS")
    word_count: int = Field(description="Total word count")
    estimated_duration_seconds: float = Field(description="Estimated narration duration")
    structure_type: ScriptStructureType = Field(description="Which script structure was used")
    visual_plan: list[VisualCue] = Field(description="Visual directions per section")
    caption_lines: list[str] = Field(description="Script broken into short caption lines")
    title_ideas: list[str] = Field(min_length=3, max_length=5, description="3-5 title options")
    description: str = Field(description="Video description")
    hashtags: list[str] = Field(description="Relevant hashtags")
    source_list: list[str] = Field(description="Sources used/credited")
    commentary_notes: str = Field(description="Notes on what original commentary was added")


# ---------------------------------------------------------------------------
# Quality Models
# ---------------------------------------------------------------------------

class QualityCheck(BaseModel):
    """Individual quality check result."""
    name: str
    passed: bool
    score: int = Field(ge=0, le=100)
    reason: str
    suggestion: Optional[str] = None


class QualityReport(BaseModel):
    """Full quality gate report."""
    verdict: QualityVerdict
    overall_score: int = Field(ge=0, le=100)
    checks: list[QualityCheck]
    warnings: list[str] = Field(default_factory=list)
    suggested_fixes: list[str] = Field(default_factory=list)
    safe_to_post: bool = Field(default=False, description="Whether manual review can be skipped (rarely true)")


# ---------------------------------------------------------------------------
# Voice / Caption Models
# ---------------------------------------------------------------------------

class VoiceConfig(BaseModel):
    """Configuration for TTS generation."""
    voice: str = "nova"
    model: str = "tts-1-hd"
    speed: float = 1.05
    tone: StoryTone = StoryTone.GENERAL


class WordTimestamp(BaseModel):
    """A single word with its timing."""
    word: str
    start: float
    end: float


class CaptionLine(BaseModel):
    """A single caption display unit."""
    text: str
    start_time: float
    end_time: float
    words: list[WordTimestamp] = Field(default_factory=list)
    highlighted_words: list[str] = Field(default_factory=list, description="Words to emphasize")


# ---------------------------------------------------------------------------
# Video Models
# ---------------------------------------------------------------------------

class VideoSection(BaseModel):
    """A timed section of the video with visual and audio info."""
    name: str = Field(description="Section name (hook, explanation, etc.)")
    start_time: float
    end_time: float
    text_overlay: Optional[str] = None
    visual_cue: Optional[VisualCue] = None
    captions: list[CaptionLine] = Field(default_factory=list)


class VideoConfig(BaseModel):
    """Configuration for video rendering."""
    width: int = 1080
    height: int = 1920
    fps: int = 30
    template: VisualTemplate = VisualTemplate.DARK_GRADIENT
    accent_color: tuple[int, int, int] = (0, 200, 255)  # Cyan default


# ---------------------------------------------------------------------------
# Metadata Models
# ---------------------------------------------------------------------------

class VideoMetadata(BaseModel):
    """Generated metadata for a video package."""
    title_options: list[str] = Field(min_length=3, max_length=5)
    description: str
    hashtags: list[str]
    source_links: list[str]
    ai_disclosure: str = Field(
        default="This video uses AI-generated narration and AI-assisted editing. "
        "All facts are sourced and credited. Manual review was performed before posting."
    )
    recommended_platform: str = Field(default="YouTube Shorts")
    review_warnings: list[str] = Field(default_factory=list)
    manual_review_required: bool = Field(default=True)


# ---------------------------------------------------------------------------
# Output Package Model
# ---------------------------------------------------------------------------

class OutputPackage(BaseModel):
    """Complete output package for a generated video."""
    package_id: str = Field(description="Unique ID: YYYY-MM-DD_story-slug")
    created_at: datetime = Field(default_factory=datetime.now)
    story: RawStory
    score: StoryScore
    script: GeneratedScript
    quality_report: QualityReport
    metadata: VideoMetadata
    voice_config: VoiceConfig

    # File paths (populated after generation)
    output_dir: Optional[str] = None
    video_path: Optional[str] = None
    audio_path: Optional[str] = None
    script_path: Optional[str] = None
    captions_srt_path: Optional[str] = None
    captions_ass_path: Optional[str] = None
    metadata_path: Optional[str] = None
    sources_path: Optional[str] = None
    quality_report_path: Optional[str] = None
    thumbnail_path: Optional[str] = None

    # Review status
    review_status: ReviewStatus = Field(default=ReviewStatus.PENDING)
    review_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# LLM Response Models (for Structured Output)
# ---------------------------------------------------------------------------

class LLMStoryScore(BaseModel):
    """Model for GPT-4o structured scoring output."""
    freshness: int = Field(ge=0, le=100)
    source_credibility: int = Field(ge=0, le=100)
    relevance: int = Field(ge=0, le=100)
    viral_potential: int = Field(ge=0, le=100)
    educational_value: int = Field(ge=0, le=100)
    business_angle: int = Field(ge=0, le=100)
    visual_potential: int = Field(ge=0, le=100)
    explainability: int = Field(ge=0, le=100)
    should_accept: bool
    rejection_reasons: list[str]
    detected_category: str
    detected_tone: str
    reasoning: str = Field(description="Brief explanation of scoring decisions")


class LLMScriptOutput(BaseModel):
    """Model for GPT-4o structured script generation output."""
    hook: str
    hook_card: str = Field(
        default="",
        description=(
            "4–6 word VISUAL headline for the on-screen overlay — NOT the spoken hook. "
            "Punchy, shock-value, all-caps style. E.g. 'BTC LOST $8B OVERNIGHT', "
            "'SEC APPROVES ETH FUND', 'SOLANA CROSSES $200 TODAY'."
        )
    )
    main_explanation: str
    why_it_matters: str
    student_dev_angle: str
    closing_line: str
    full_script: str
    caption_lines: list[str]
    visual_plan: list[VisualCue]
    title_ideas: list[str]
    description: str
    hashtags: list[str]
    source_list: list[str]
    commentary_notes: str
    structure_type: str
    word_count: int
    estimated_duration_seconds: float


class LLMQualityCheck(BaseModel):
    """Model for GPT-4o structured quality assessment."""
    is_just_summary: bool
    has_original_commentary: bool
    has_why_it_matters: bool
    source_similarity_concern: bool
    hook_strength: int = Field(ge=0, le=100)
    claim_exaggeration_risk: bool
    title_is_misleading: bool
    sources_present: bool
    story_is_recent: bool
    feels_like_ai_slop: bool
    overall_score: int = Field(ge=0, le=100)
    verdict: str  # "approved", "rejected", "needs_revision"
    reasons: list[str]
    suggested_fixes: list[str]
    warnings: list[str]


class LLMMetadataOutput(BaseModel):
    """Model for GPT-4o structured metadata generation."""
    title_options: list[str]
    description: str
    hashtags: list[str]
    platform_recommendation: str
    review_warnings: list[str]
    manual_review_required: bool
