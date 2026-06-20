"""
Pipeline orchestrator — connects all phases of the production system.

This is the main entry point that coordinates:
  1. News discovery
  2. Story scoring
  3. Dedup checking
  4. Script generation
  5. Quality gate
  6. Voiceover
  7. Caption alignment
  8. Video rendering
  9. Metadata generation
  10. Output packaging
"""

import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from openai import OpenAI
from slugify import slugify

from src.captions.aligner import WhisperAligner
from src.captions.formatter import CaptionFormatter
from src.discovery.newsdata import NewsDataClient
from src.discovery.rss import RSSClient
from src.memory.database import Database
from src.memory.dedup import DedupEngine
from src.metadata.generator import MetadataGenerator
from src.models.schemas import (
    GeneratedScript,
    OutputPackage,
    QualityVerdict,
    ReviewStatus,
    ScoredStory,
    ScriptStructureType,
    VisualTemplate,
)
from src.scoring.scorer import StoryScorer
from src.scripts.generator import ScriptGenerator
from src.scripts.quality import QualityGate
from src.scripts.structures import get_all_structure_types, get_structure
from src.video.renderer import VideoRenderer
from src.video.broll import BRollAgent
from src.video.templates import get_all_template_types
from src.voice.tts import TTSEngine

logger = logging.getLogger(__name__)


class Pipeline:
    """Main orchestrator for the news shorts production pipeline."""

    def __init__(self, config_path: str = "config.yaml"):
        # Load environment
        load_dotenv()

        # Load config
        self.config = self._load_config(config_path)

        # Groq client — fast, used for scoring / quality / metadata / b-roll (gpt-oss-120b)
        self._groq_client, self._groq_model, self._groq_keys, self._groq_idx = \
            self._build_groq_client()

        # NVIDIA client — best quality, used for script writing (deepseek-v4-flash)
        self._nvidia_client, self._nvidia_model, self._nvidia_keys, self._nvidia_idx = \
            self._build_nvidia_client()

        # openai_client kept as legacy ref (TTS engine, broll agent init)
        self.openai_client = self._groq_client or OpenAI(api_key="placeholder")

        # Initialize components
        self.db = Database(db_path=self.config.get("db_path", "./data/news_shorts.db"))
        self.dedup = DedupEngine(self.db)

        # Discovery
        discovery_config = self.config.get("discovery", {})
        newsdata_key = os.getenv("NEWSDATA_API_KEY")
        self.newsdata_client = NewsDataClient(newsdata_key, discovery_config) if newsdata_key else None
        self.rss_client = RSSClient(discovery_config)

        # Analytics — fetch channel insights to inform story scoring
        from src.analytics.youtube_channel import YouTubeChannelAnalytics
        from src.analytics import zernio
        analytics_insights: dict = {}
        yt_analytics = YouTubeChannelAnalytics(api_key=os.getenv("YOUTUBE_API_KEY"))
        channel_id = os.getenv("YOUTUBE_CHANNEL_ID", "")
        if not channel_id:
            channel_handle = self.config.get("channel", {}).get("youtube_handle", "")
            if channel_handle:
                channel_id = yt_analytics.get_channel_id(channel_handle) or ""
        if channel_id:
            try:
                analytics_insights = yt_analytics.get_performance_insights(channel_id)
                logger.info(f"Analytics loaded: {analytics_insights.get('total_videos_analyzed', 0)} videos, "
                            f"top kws: {[k for k,_ in analytics_insights.get('top_keywords', [])[:5]]}")
            except Exception as e:
                logger.warning(f"Analytics fetch failed (non-fatal): {e}")

        # Scoring (analytics-informed)
        scoring_config = {
            **self.config.get("scoring", {}),
            **self.config.get("scripts", {}),
            "freshness_hours": discovery_config.get("max_age_hours", 48),
        }
        # Scoring: Groq gpt-oss-120b (fast, analytical)
        self.scorer = StoryScorer(self._groq_client or self.openai_client, scoring_config, analytics_insights=analytics_insights)

        # Script generation: NVIDIA deepseek-v4-flash (best creative quality)
        scripts_config = {
            **self.config.get("scripts", {}),
            "channel_name": self.config.get("channel", {}).get("name", "TechPulse Shorts"),
            "llm_model": self._nvidia_model or self._groq_model or "openai/gpt-oss-120b",
        }
        self.script_generator = ScriptGenerator(
            self._nvidia_client or self._groq_client or self.openai_client, scripts_config)

        # Quality gate: Groq gpt-oss-120b (analytical, fast)
        quality_config = {
            **self.config.get("quality", {}),
            **self.config.get("scripts", {}),
            "llm_model": self._groq_model or "openai/gpt-oss-120b",
        }
        self.quality_gate = QualityGate(self._nvidia_client or self._groq_client or self.openai_client, quality_config)

        # Voice
        voice_config = self.config.get("voice", {})
        self.tts_engine = TTSEngine(self.openai_client, voice_config)

        # Captions
        caption_config = self.config.get("captions", {})
        self.aligner = WhisperAligner(caption_config)
        self.caption_formatter = CaptionFormatter(caption_config)

        # Video
        video_config = self.config.get("video", {})
        self.video_renderer = VideoRenderer({
            **video_config,
            "generate_thumbnail": self.config.get("output", {}).get("generate_thumbnail", True),
        })

        # Metadata: NVIDIA GLM-5.1 (saves Groq TPD for scoring + quality gate)
        meta_config = {**self.config.get("scripts", {}), "llm_model": "z-ai/glm-5.1"}
        self.metadata_generator = MetadataGenerator(self._nvidia_client or self._groq_client or self.openai_client, meta_config)

        # Output
        self.output_folder = self.config.get("output", {}).get("folder", "./output")
        self.render_video = self.config.get("output", {}).get("render_video", True)
        self.channel_name = self.config.get("channel", {}).get("name", "TechPulse Shorts")
        self.max_retries = self.config.get("scripts", {}).get("max_retries", 2)

        # Distribution / Neural Drop promotion
        self.distribution = self.config.get("distribution", {})

        logger.info("Pipeline initialized")

    def _build_nvidia_client(self):
        """NVIDIA NIM — GLM-5.1 for script writing. Uses RotatingKeyClient to
        automatically cycle through all available keys when one hits 429."""
        from src.utils.llm import RotatingKeyClient
        keys = []
        # GLM dedicated keys first, then main NVIDIA keys
        for prefix in ("NVIDIA_GLM_KEY", "NVIDIA_API_KEY"):
            for i in range(1, 11):
                k = os.getenv(f"{prefix}_{i}", "")
                if k and k not in keys:
                    keys.append(k)
        for var in ("NVIDIA_API_KEY",):
            k = os.getenv(var, "")
            if k and k not in keys:
                keys.append(k)
        if not keys:
            return None, None, [], 0
        client = RotatingKeyClient(keys, base_url="https://integrate.api.nvidia.com/v1")
        model = "z-ai/glm-5.1"
        logger.info(f"NVIDIA NIM enabled: {len(keys)} key(s) with rotation, model={model}")
        return client, model, keys, 0

    def _build_groq_client(self):
        """Groq — gpt-oss-120b for scoring/quality/metadata/b-roll (fast, analytical)."""
        from src.utils.llm import RotatingKeyClient
        keys = []
        for var in ("GROQ_API_KEY_1", "GROQ_API_KEY_2", "GROQ_API_KEY_3", "GROQ_API_KEY"):
            k = os.getenv(var, "")
            if k and k not in keys:
                keys.append(k)
        if not keys:
            return None, None, [], 0
        client = RotatingKeyClient(keys, base_url="https://api.groq.com/openai/v1")
        model = "openai/gpt-oss-120b"
        logger.info(f"Groq enabled: {len(keys)} key(s) with rotation, model={model}")
        return client, model, keys, 0

    def _load_config(self, config_path: str) -> dict:
        """Load YAML configuration file."""
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"Config file not found: {config_path}, using defaults")
            return {}
        with open(path) as f:
            return yaml.safe_load(f) or {}

    # =========================================================================
    # Main Pipeline Methods
    # =========================================================================

    def generate(
        self,
        topic: Optional[str] = None,
        count: int = 1,
        overrides: Optional[dict] = None
    ) -> list[OutputPackage]:
        """
        Full pipeline: discover → score → script → voice → render → package.
        """
        topic = topic or (overrides.get("topic") if overrides else None)
        logger.info(f"=== Starting pipeline: count={count}, topic={topic or 'auto'} ===")

        # Step 1: Discover stories
        stories = []
        accepted = []
        
        is_direct_url = topic and (topic.startswith("http://") or topic.startswith("https://"))
        
        if is_direct_url:
            logger.info(f"Direct URL provided, bypassing discovery and scoring: {topic}")
            from src.discovery.url_parser import UrlParser
            from src.models.schemas import ScoredStory, StoryScore
            
            parsed_story = UrlParser.parse_url(topic)
            if not parsed_story:
                logger.error("Failed to parse URL. Pipeline complete.")
                return []
                
            stories = [parsed_story]
            
            # Create a mock perfect score since the user specifically requested this URL
            mock_score = StoryScore(
                tech_relevance=10,
                broad_appeal=10,
                visual_potential=10,
                novelty=10,
                total_score=100,
                reasoning="Directly requested by user via URL.",
                category="general_tech"
            )
            accepted = [ScoredStory(story=parsed_story, score=mock_score, accepted=True, detected_tone="general")]
        else:
            stories = self.discover(topic=topic)
            if overrides and overrides.get("custom_video_url"):
                for s in stories:
                    s.url = overrides.get("custom_video_url")
                    
            if not stories:
                logger.warning("No stories discovered. Pipeline complete.")
                return []

            # Step 2: Pre-filter to top 20 by heuristic before expensive LLM scoring
            stories = self._heuristic_prefilter(stories, top_n=20)
            logger.info(f"Pre-filtered to {len(stories)} stories for LLM scoring")

            # Step 3: Score and filter
            scored = self.score(stories)
            accepted = [s for s in scored if s.accepted]
            logger.info(f"Accepted {len(accepted)}/{len(scored)} stories")

            if not accepted:
                logger.warning("No stories passed scoring. Pipeline complete.")
                return []

        # Step 3: Generate videos for top stories
        # Try extra candidates if a story has no video available
        from src.video.smart_broll import NoVideoAvailable
        packages = []
        candidates = list(accepted)  # full ranked list to draw from
        attempted = 0
        for scored_story in candidates:
            if len(packages) >= count:
                break
            attempted += 1
            try:
                package = self.process_story(scored_story, overrides)
                if package:
                    packages.append(package)
                    logger.info(f"✓ Generated package: {package.package_id}")
            except NoVideoAvailable as e:
                logger.warning(f"No video for story, trying next: {e}")
                continue
            except Exception as e:
                logger.error(f"Failed to process story: {e}", exc_info=True)
                continue

        logger.info(f"=== Pipeline complete: {len(packages)} packages generated ===")
        return packages

    def discover(
        self,
        topic: Optional[str] = None,
        max_results: int = 50,
    ) -> list:
        """Discover news stories from configured sources."""
        from src.models.schemas import RawStory

        all_stories: list[RawStory] = []
        provider = self.config.get("discovery", {}).get("provider", "newsdata")

        if provider in ("newsdata", "both") and self.newsdata_client:
            try:
                stories = self.newsdata_client.search_stories(topic, max_results)
                all_stories.extend(stories)
                logger.info(f"NewsData.io: found {len(stories)} stories")
            except Exception as e:
                logger.error(f"NewsData.io search failed: {e}")

        if provider in ("rss", "both") or (provider == "newsdata" and not self.newsdata_client):
            try:
                stories = self.rss_client.search_stories(topic, max_results)
                all_stories.extend(stories)
                logger.info(f"RSS: found {len(stories)} stories")
            except Exception as e:
                logger.error(f"RSS search failed: {e}")

        # Dedup against memory
        fresh_stories = []
        for story in all_stories:
            is_dup, reason = self.dedup.is_duplicate_story(story)
            if is_dup:
                logger.debug(f"Skipping duplicate: {reason} — {story.title[:60]}")
            else:
                fresh_stories.append(story)

        logger.info(f"After dedup: {len(fresh_stories)}/{len(all_stories)} stories are fresh")
        return fresh_stories

    def _heuristic_prefilter(self, stories, top_n: int = 10):
        """Fast pre-filter before expensive LLM scoring. Ranks by freshness + keyword match."""
        from datetime import datetime, timezone
        import re

        high_value = {"bitcoin", "ethereum", "solana", "btc", "eth", "etf", "regulation", "sec",
                      "hack", "stablecoin", "defi", "institutional", "coinbase", "binance"}

        # Hard-reject presale shills, price predictions, and opinion "top picks" before LLM scoring
        shill_patterns = re.compile(
            r"\b(presale|top \d+ crypto|cryptos? to buy|price prediction|could .* be|"
            r"right pick|losing momentum|gains momentum|collects \$|raised \$.*presale|"
            r"pepeto|pepe2|meme ?coin presale)\b",
            re.IGNORECASE
        )

        now = datetime.now(timezone.utc)

        def _score(story):
            # Freshness: up to 50 pts (24h = 50, 48h = 0)
            try:
                pub = story.published_at
                if pub and pub.tzinfo is None:
                    from datetime import timezone as _tz
                    pub = pub.replace(tzinfo=_tz.utc)
                age_hours = (now - pub).total_seconds() / 3600 if pub else 48
            except Exception:
                age_hours = 48
            freshness = max(0, 50 - age_hours * (50 / 48))

            # Keyword match: up to 50 pts
            words = set(re.findall(r"\w+", (story.title or "").lower()))
            kw_score = min(50, len(words & high_value) * 15)

            return freshness + kw_score

        stories = [s for s in stories if not shill_patterns.search(s.title or "")]
        ranked = sorted(stories, key=_score, reverse=True)
        return ranked[:top_n]

    def score(self, stories) -> list[ScoredStory]:
        """Score and rank stories."""
        logger.info(f"Scoring {len(stories)} stories...")
        return self.scorer.score_stories(stories)

    def process_story(self, scored_story: ScoredStory, overrides: Optional[dict] = None) -> Optional[OutputPackage]:
        """
        Process a single scored story through the full pipeline.

        Returns None if the story fails quality checks after retries.
        """
        story = scored_story.story
        logger.info(f"\n--- Processing: {story.title[:70]} ---")

        # Pick structure and template (avoiding repeats)
        structure_type = self.dedup.get_least_used_structure(get_all_structure_types())
        structure = get_structure(ScriptStructureType(structure_type))

        accent_colors = self.config.get("video", {}).get(
            "accent_colors", [[0, 200, 255]]
        )
        accent_colors_tuples = [tuple(c) for c in accent_colors]

        template_type, _ = self.dedup.get_least_used_template(
            get_all_template_types(),
            accent_colors_tuples,
        )
        accent_color = (255, 255, 255)
        if overrides and overrides.get("accent_color_hex"):
            hex_c = overrides.get("accent_color_hex").lstrip('#')
            if len(hex_c) == 6:
                accent_color = tuple(int(hex_c[i:i+2], 16) for i in (0, 2, 4))

        recent_hooks = self.db.get_recent_hooks(limit=15)

        # Step 1: Generate script
        logger.info(f"Generating script (structure: {structure.name})...")
        script = self.script_generator.generate_script(
            scored_story, structure, recent_hooks
        )
        logger.info(f"Script: {script.word_count} words, ~{script.estimated_duration_seconds:.1f}s")

        # Step 2: Quality gate (with retries)
        quality_report = self.quality_gate.check_script(script, scored_story)
        retries = 0

        while quality_report.verdict != QualityVerdict.APPROVED and retries < self.max_retries:
            retries += 1
            logger.warning(
                f"Quality check: {quality_report.verdict.value} (attempt {retries}/{self.max_retries})"
            )

            if quality_report.verdict == QualityVerdict.REJECTED and retries >= self.max_retries:
                logger.error(f"Script rejected after {retries} attempts. Skipping story.")
                return None

            # Revise script
            feedback = quality_report.suggested_fixes + [
                c.reason for c in quality_report.checks if not c.passed
            ]
            logger.info(f"Revising script with {len(feedback)} fixes...")

            script = self.script_generator.regenerate_with_feedback(
                scored_story, structure, script, feedback, recent_hooks
            )
            quality_report = self.quality_gate.check_script(script, scored_story)

        if quality_report.verdict == QualityVerdict.REJECTED:
            logger.error("Script rejected after all retries.")
            return None

        logger.info(f"Quality gate: {quality_report.verdict.value} ({quality_report.overall_score}/100)")

        # Step 3: Create output directory
        date_str = datetime.now().strftime("%Y-%m-%d")
        slug = slugify(story.title[:50])
        package_id = f"{date_str}_{slug}"
        output_dir = Path(self.output_folder) / package_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # Steps 4+5: B-roll and TTS run in parallel (both independent of each other)
        broll_source = "tts_only"
        yt_audio_path = None
        media_paths: dict[str, str] = {}
        audio_path = str(output_dir / "voiceover.mp3")
        voice_override = overrides.get("tts_voice") if overrides else None

        from concurrent.futures import ThreadPoolExecutor

        def _acquire_broll():
            if not self.render_video:
                return {}, "tts_only", None
            logger.info("Acquiring b-roll media...")
            from src.video.smart_broll import SmartBRollAgent
            agent = SmartBRollAgent(str(output_dir), self.openai_client)
            return agent.acquire_media(script, scored_story.story, accent_color)

        def _generate_tts():
            logger.info("Generating TTS voiceover...")
            return self.tts_engine.generate_voiceover(
                script_text=script.full_script,
                output_path=audio_path,
                tone=scored_story.detected_tone,
                voice_override=voice_override,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_broll = pool.submit(_acquire_broll)
            f_tts = pool.submit(_generate_tts)
            media_paths, broll_source, yt_audio_path = f_broll.result()
            voice_config = f_tts.result()

        # When YouTube b-roll downloaded successfully, use its audio instead of TTS.
        # This gives authentic news audio and avoids the synthetic voice entirely.
        if yt_audio_path and Path(yt_audio_path).exists():
            logger.info(f"Using YouTube audio instead of TTS: {yt_audio_path}")
            audio_path = yt_audio_path

        # Step 6: Get audio duration
        audio_duration = self._get_audio_duration(audio_path)
        if audio_duration is None:
            audio_duration = script.estimated_duration_seconds
        logger.info(f"Audio duration: {audio_duration:.1f}s")

        # Step 7: Align captions
        logger.info("Aligning captions...")
        word_timestamps = self.aligner.align_audio(audio_path, script.full_script)
        caption_lines = self.caption_formatter.create_caption_lines(word_timestamps)

        # Step 8: Export caption files
        srt_path = self.caption_formatter.export_srt(
            caption_lines, str(output_dir / "captions.srt")
        )
        ass_path = self.caption_formatter.export_ass(
            caption_lines, str(output_dir / "captions.ass"),
            video_width=self.video_renderer.width,
            video_height=self.video_renderer.height,
            accent_color=accent_color,
        )

        # Step 9: Generate metadata (now uses voice_config from parallel TTS above)
        logger.info("Generating metadata...")
        metadata = self.metadata_generator.generate_metadata(
            script, scored_story, voice_config
        )

        # Step 10: Render video (if enabled)
        video_path = None
        thumbnail_path = None

        if self.render_video and media_paths:
            logger.info("Rendering video...")
            render_paths = self.video_renderer.render(
                output_dir=str(output_dir),
                audio_path=audio_path,
                script=script,
                caption_lines=caption_lines,
                media_paths=media_paths,
                total_duration=audio_duration,
                template_type=VisualTemplate(template_type),
                accent_color=accent_color,
                channel_name=self.channel_name,
                source_name=story.source_name,
                cta_text=self.distribution.get("cta_prompt", "Get the daily AI briefing >>"),
                cta_link=self.distribution.get("link", "bit.ly/neural-drop"),
                cta_duration=self.distribution.get("cta_duration_seconds", 3.5),
                show_cta=self.distribution.get("show_cta_overlay", True),
            )
            video_path = render_paths.get("video")
            thumbnail_path = render_paths.get("thumbnail")

        # Step 10: Save all files
        self._save_package_files(
            output_dir, script, quality_report, metadata,
            scored_story, voice_config
        )

        # Step 11: Record in database
        self.dedup.record_usage(
            story=story,
            hook_text=script.sections.hook,
            structure_type=structure_type,
            template_type=template_type,
            accent_color=accent_color,
            score_total=scored_story.score.total_score,
            score_data=scored_story.score.model_dump(),
        )

        # Build output package
        package = OutputPackage(
            package_id=package_id,
            story=story,
            score=scored_story.score,
            script=script,
            quality_report=quality_report,
            metadata=metadata,
            voice_config=voice_config,
            output_dir=str(output_dir),
            video_path=video_path,
            audio_path=audio_path,
            script_path=str(output_dir / "script.json"),
            captions_srt_path=srt_path,
            captions_ass_path=ass_path,
            metadata_path=str(output_dir / "metadata.json"),
            sources_path=str(output_dir / "sources.json"),
            quality_report_path=str(output_dir / "quality_report.json"),
            thumbnail_path=thumbnail_path,
        )

        # Zernio analytics: track the published video
        try:
            from src.analytics import zernio as _z
            _z.track_video_published(
                video_id=package_id,
                title=story.title,
                story_topic=scored_story.detected_category.value,
                broll_source=broll_source,
                duration_seconds=audio_duration,
                quality_score=quality_report.overall_score,
            )
        except Exception as _ze:
            logger.debug(f"Zernio tracking skipped: {_ze}")

        logger.info(f"✓ Package complete: {package_id}")
        return package

    # =========================================================================
    # Partial Pipeline Methods (for regeneration)
    # =========================================================================

    def regenerate_voice(self, package_dir: str) -> str:
        """Regenerate voiceover for an existing package."""
        pkg_dir = Path(package_dir)
        script_data = json.loads((pkg_dir / "script.json").read_text())

        audio_path = str(pkg_dir / "voiceover.mp3")
        self.tts_engine.generate_voiceover(
            script_text=script_data["full_script"],
            output_path=audio_path,
        )
        return audio_path

    def regenerate_captions(self, package_dir: str) -> tuple[str, str]:
        """Regenerate captions for an existing package."""
        pkg_dir = Path(package_dir)
        audio_path = str(pkg_dir / "voiceover.mp3")
        script_data = json.loads((pkg_dir / "script.json").read_text())

        word_timestamps = self.aligner.align_audio(audio_path, script_data["full_script"])
        caption_lines = self.caption_formatter.create_caption_lines(word_timestamps)

        srt_path = self.caption_formatter.export_srt(
            caption_lines, str(pkg_dir / "captions.srt")
        )
        ass_path = self.caption_formatter.export_ass(
            caption_lines, str(pkg_dir / "captions.ass")
        )
        return srt_path, ass_path

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _save_package_files(
        self, output_dir, script, quality_report, metadata,
        scored_story, voice_config,
    ) -> None:
        """Save all package JSON files."""
        output_dir = Path(output_dir)

        # Script
        (output_dir / "script.json").write_text(
            json.dumps(script.model_dump(), indent=2, default=str)
        )

        # Quality report
        (output_dir / "quality_report.json").write_text(
            json.dumps(quality_report.model_dump(), indent=2, default=str)
        )

        # Metadata (with review status)
        meta_dict = metadata.model_dump()
        meta_dict["review_status"] = "pending"
        (output_dir / "metadata.json").write_text(
            json.dumps(meta_dict, indent=2, default=str)
        )

        # Sources
        (output_dir / "sources.json").write_text(
            json.dumps({
                "story_url": scored_story.story.url,
                "source_name": scored_story.story.source_name,
                "sources": script.source_list,
                "ai_disclosure": metadata.ai_disclosure,
                "voice_config": voice_config.model_dump(),
            }, indent=2, default=str)
        )

    def _get_audio_duration(self, audio_path: str) -> Optional[float]:
        """Get audio duration using ffprobe."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    audio_path,
                ],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
        except (subprocess.SubprocessError, ValueError, FileNotFoundError):
            pass
        return None

    def re_render_package(self, package_id: str, overrides: dict, progress_callback=None) -> None:
        """Re-render an existing package with overrides."""
        logger.info(f"Re-rendering package {package_id} with overrides: {overrides}")
        
        # Find package directory
        pkg_dir = None
        for base_dir in ["./output", "./demo/example_output"]:
            d = Path(base_dir) / package_id
            if d.exists():
                pkg_dir = d
                break
                
        if not pkg_dir:
            raise ValueError(f"Package {package_id} not found")
            
        # 1. Load current state
        from src.models.schemas import GeneratedScript, RawStory, VisualTemplate
        
        script_data = json.loads((pkg_dir / "script.json").read_text())
        # Use model_construct to avoid validation errors on older script formats
        script = GeneratedScript.model_construct(**script_data)
        
        # Convert nested dicts to objects if needed
        from src.models.schemas import ScriptSection
        if isinstance(script.sections, dict):
            script.sections = ScriptSection(**script.sections)
            
        meta_data = json.loads((pkg_dir / "metadata.json").read_text())
        audio_path = str(pkg_dir / "voiceover.mp3")
        
        # 2. Apply text edits
        text_changed = False
        if overrides.get("script_text"):
            new_text = overrides.get("script_text")
            if new_text != script.full_script:
                script.full_script = new_text
                text_changed = True
                (pkg_dir / "script.json").write_text(
                    json.dumps(script.model_dump(), indent=2, default=str)
                )

        # 3. Handle Voice & Audio
        voice_override = overrides.get("tts_voice")
        needs_audio = text_changed or voice_override
        
        if needs_audio:
            logger.info("Regenerating voiceover due to script/voice change...")
            self.tts_engine.generate_voiceover(
                script_text=script.full_script,
                output_path=audio_path,
                voice_override=voice_override,
            )
            
            # Realign captions
            logger.info("Realigning captions...")
            word_timestamps = self.aligner.align_audio(audio_path, script.full_script)
            caption_lines = self.caption_formatter.create_caption_lines(word_timestamps)
            self.caption_formatter.export_srt(caption_lines, str(pkg_dir / "captions.srt"))
        else:
            logger.info("Realigning existing audio to get caption objects...")
            word_timestamps = self.aligner.align_audio(audio_path, script.full_script)
            caption_lines = self.caption_formatter.create_caption_lines(word_timestamps)
            
        # 4. Handle Visuals
        accent_color = (255, 255, 255)
        if overrides.get("accent_color_hex"):
            hex_c = overrides.get("accent_color_hex").lstrip('#')
            if len(hex_c) == 6:
                accent_color = tuple(int(hex_c[i:i+2], 16) for i in (0, 2, 4))
                
        # Handle custom video override
        if overrides.get("custom_video_url"):
            logger.info("Regenerating B-Roll with custom URL...")
            from src.video.smart_broll import SmartBRollAgent
            broll_agent = SmartBRollAgent(str(pkg_dir), self.openai_client)
            story = RawStory(
                title=meta_data.get("title_options", [""])[0],
                url=overrides.get("custom_video_url"),
                published_at="2024-01-01",
                source_name="Custom",
                content="Custom"
            )
            media_paths = broll_agent.acquire_media(script, story, accent_color)
        else:
            # Use existing media
            media_paths = {}
            for cue in script.visual_plan:
                section_name = cue.get("section") if isinstance(cue, dict) else cue.section
                p = pkg_dir / "media" / f"{section_name}.mp4"
                if p.exists():
                    media_paths[section_name] = str(p)
                else:
                    p2 = pkg_dir / "media" / f"{section_name}.png"
                    if p2.exists():
                        media_paths[section_name] = str(p2)
                        
        audio_duration = self._get_audio_duration(audio_path) or script.estimated_duration_seconds
        
        # 5. Render Video
        logger.info("Re-rendering final video...")
        self.video_renderer.render(
            output_dir=str(pkg_dir),
            audio_path=audio_path,
            script=script,
            caption_lines=caption_lines,
            media_paths=media_paths,
            total_duration=audio_duration,
            template_type=VisualTemplate.SPLIT_SCREEN,
            accent_color=accent_color,
            channel_name=self.channel_name,
            source_name="",
            progress_callback=progress_callback,
            cta_text=self.distribution.get("cta_prompt", "Get the daily AI briefing >>"),
            cta_link=self.distribution.get("link", "bit.ly/neural-drop"),
            cta_duration=self.distribution.get("cta_duration_seconds", 3.5),
            show_cta=self.distribution.get("show_cta_overlay", True),
        )
        logger.info(f"Re-render of {package_id} complete!")

    def get_stats(self) -> dict:
        """Get pipeline statistics."""
        return self.db.get_stats()
