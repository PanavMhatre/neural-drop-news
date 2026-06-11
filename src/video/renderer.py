"""
Video renderer — high-level orchestrator for video production.

Coordinates the compositor, captions, and audio to produce
the final video file.
"""

import logging
from pathlib import Path
from typing import Optional

from src.captions.formatter import CaptionFormatter
from src.models.schemas import CaptionLine, GeneratedScript, VisualTemplate
from src.video.compositor import FrameCompositor, generate_thumbnail
from src.video.templates import TemplateConfig, get_template

logger = logging.getLogger(__name__)


class VideoRenderer:
    """High-level video rendering orchestrator."""

    def __init__(self, config: dict):
        self.config = config
        self.width = config.get("width", 1080)
        self.height = config.get("height", 1920)
        self.fps = config.get("fps", 30)
        self.show_progress_bar = config.get("show_progress_bar", True)
        self.generate_thumb = config.get("generate_thumbnail", True)

        self.compositor = FrameCompositor(
            width=self.width,
            height=self.height,
            fps=self.fps,
        )

    def render(
        self,
        output_dir: str,
        audio_path: str,
        script: GeneratedScript,
        caption_lines: list[CaptionLine],
        media_paths: dict[str, str],
        total_duration: float,
        template_type: VisualTemplate,
        accent_color: tuple[int, int, int],
        channel_name: str = "TechPulse Shorts",
        source_name: str = "",
        progress_callback = None,
        cta_text: str = "Get the daily AI briefing >>",
        cta_link: str = "bit.ly/neural-drop",
        cta_duration: float = 3.5,
        show_cta: bool = True,
    ) -> dict[str, str]:
        """
        Render the complete video package.

        Args:
            output_dir: Directory to save output files.
            audio_path: Path to voiceover audio.
            script: Generated script.
            caption_lines: Formatted caption lines.
            media_paths: Paths to section b-roll media.
            total_duration: Video duration in seconds.
            template_type: Which visual template to use.
            accent_color: RGB accent color.
            channel_name: Channel name for watermark.
            source_name: Source name for footer.

        Returns:
            Dict with paths: {"video": ..., "thumbnail": ...}
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        template = get_template(template_type)
        video_path = str(output_path / "video.mp4")
        paths = {"video": video_path}

        # Render video
        logger.info(f"Starting video render: {template.name} + {accent_color}")

        self.compositor.render_video(
            output_path=video_path,
            audio_path=audio_path,
            template=template,
            accent_color=accent_color,
            script=script,
            caption_lines=caption_lines,
            media_paths=media_paths,
            total_duration=total_duration,
            channel_name=channel_name,
            source_text=source_name,
            show_progress_bar=self.show_progress_bar,
            progress_callback=progress_callback,
            cta_text=cta_text,
            cta_link=cta_link,
            cta_duration=cta_duration,
            show_cta=show_cta,
        )

        # Generate thumbnail
        if self.generate_thumb:
            thumbnail_path = str(output_path / "thumbnail.png")
            generate_thumbnail(
                output_path=thumbnail_path,
                template=template,
                accent_color=accent_color,
                hook_text=script.sections.hook,
                channel_name=channel_name,
                width=self.width,
                height=self.height,
            )
            paths["thumbnail"] = thumbnail_path

        return paths
