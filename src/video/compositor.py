"""
Frame compositor — generates video frames and pipes to FFmpeg.

This is the core rendering engine that creates each frame using Pillow
and streams raw pixel data to FFmpeg for encoding. It handles all visual
composition: background, text, captions, progress bar, and animations.
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional

import cv2
from PIL import Image, ImageFont

from src.captions.formatter import CaptionFormatter
from src.models.schemas import CaptionLine, GeneratedScript, VisualCue
from src.video import animations as anim
from src.video import elements as elem
from src.video.templates import TemplateConfig

logger = logging.getLogger(__name__)


class FrameCompositor:
    """Generates and composes video frames, pipes to FFmpeg."""

    def __init__(
        self,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        font_dir: str = "./assets/fonts",
    ):
        self.width = width
        self.height = height
        self.fps = fps
        self.font_dir = Path(font_dir)

        # Load fonts
        self._fonts: dict[str, ImageFont.FreeTypeFont] = {}
        self._load_fonts()

    def _load_fonts(self) -> None:
        """Load font files with fallback to default."""
        font_paths = [
            self.font_dir / "Montserrat" / "Montserrat-Black.ttf",
            self.font_dir / "Montserrat" / "Montserrat-Bold.ttf",
            self.font_dir / "Montserrat" / "Montserrat-Medium.ttf",
            self.font_dir / "Montserrat" / "Montserrat-Regular.ttf",
            Path("/System/Library/Fonts/Helvetica.ttc"),  # macOS fallback
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),  # Linux fallback
        ]

        bold_path = None
        regular_path = None
        for p in font_paths:
            if p.exists():
                if "Bold" in p.name or bold_path is None:
                    bold_path = str(p)
                if "Regular" in p.name or "Helvetica" in p.name or "DejaVu" in p.name:
                    regular_path = str(p)

        if bold_path is None:
            bold_path = regular_path
        if regular_path is None:
            regular_path = bold_path

        # Use first available font path for all sizes
        base_path = bold_path or regular_path

        if base_path:
            self._fonts["hook"] = elem.get_font(base_path, 72)
            self._fonts["body"] = elem.get_font(base_path, 44)
            self._fonts["caption"] = elem.get_font(base_path, 56)
            self._fonts["source"] = elem.get_font(regular_path or base_path, 22)
            self._fonts["watermark"] = elem.get_font(regular_path or base_path, 18)
            self._fonts["cta"] = elem.get_font(base_path, 36)
            self._fonts["cta_brand"] = elem.get_font(base_path, 64)
            self._fonts["cta_tagline"] = elem.get_font(regular_path or base_path, 28)
        else:
            # Fall back to default font at various sizes
            default = ImageFont.load_default()
            for key in ["hook", "body", "caption", "source", "watermark", "cta", "cta_brand", "cta_tagline"]:
                self._fonts[key] = default

    def render_video(
        self,
        output_path: str,
        audio_path: str,
        template: TemplateConfig,
        accent_color: tuple[int, int, int],
        script: GeneratedScript,
        caption_lines: list[CaptionLine],
        media_paths: dict[str, str],
        total_duration: float,
        channel_name: str = "TechPulse Shorts",
        source_text: str = "",
        show_progress_bar: bool = True,
        progress_callback = None,
        cta_text: str = "Get the daily AI briefing >>",
        cta_link: str = "bit.ly/neural-drop",
        cta_duration: float = 3.5,
        show_cta: bool = True,
    ) -> str:
        """
        Render the complete video by generating frames and piping to FFmpeg.

        Args:
            output_path: Path for the output MP4 file.
            audio_path: Path to the voiceover audio file.
            template: Visual template configuration.
            accent_color: RGB accent color tuple.
            script: Generated script with section content.
            caption_lines: Caption lines with timing data.
            media_paths: Dict mapping section name to image path.
            total_duration: Total video duration in seconds.
            channel_name: Channel name for watermark.
            source_text: Source credit text.
            show_progress_bar: Whether to show progress bar.

        Returns:
            Path to the rendered video file.
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        total_frames = int(total_duration * self.fps)
        logger.info(
            f"Rendering {total_frames} frames ({total_duration:.1f}s) at {self.fps}fps"
        )

        # Pre-load media images and video captures into memory
        loaded_media = {}
        video_captures = {}
        for section, path in media_paths.items():
            if Path(path).exists():
                try:
                    if path.endswith(".mp4"):
                        cap = cv2.VideoCapture(path)
                        video_captures[section] = cap
                    else:
                        loaded_media[section] = Image.open(path).convert("RGB")
                except Exception as e:
                    logger.warning(f"Failed to load media for {section}: {e}")

        # Update font sizes from template
        self._fonts["hook"] = elem.get_font(
            self._get_font_path("bold"), template.hook_font_size
        )
        self._fonts["body"] = elem.get_font(
            self._get_font_path("bold"), template.body_font_size
        )
        self._fonts["caption"] = elem.get_font(
            self._get_font_path("bold"), template.caption_font_size
        )

        # Build section timeline
        sections = self._build_section_timeline(script, total_duration)

        # Start FFmpeg process
        ffmpeg_cmd = self._build_ffmpeg_command(output_path, audio_path, total_duration)

        try:
            process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            for frame_idx in range(total_frames):
                frame_time = frame_idx / self.fps

                # Generate frame
                frame = self._render_frame(
                    frame_time=frame_time,
                    total_duration=total_duration,
                    template=template,
                    accent_color=accent_color,
                    script=script,
                    sections=sections,
                    caption_lines=caption_lines,
                    loaded_media=loaded_media,
                    video_captures=video_captures,
                    channel_name=channel_name,
                    source_text=source_text,
                    show_progress_bar=show_progress_bar,
                    cta_text=cta_text,
                    cta_link=cta_link,
                    cta_duration=cta_duration,
                    show_cta=show_cta,
                )

                # Write raw bytes to FFmpeg — catch broken pipe to surface ffmpeg's error
                try:
                    process.stdin.write(frame.tobytes())
                except (BrokenPipeError, ValueError, OSError):
                    # ffmpeg crashed — collect stderr for diagnosis
                    try:
                        _, stderr_bytes = process.communicate(timeout=10)
                        ffmpeg_err = stderr_bytes.decode(errors="replace")[-500:]
                    except Exception:
                        ffmpeg_err = "(could not collect ffmpeg stderr)"
                    raise RuntimeError(f"FFmpeg pipe closed at frame {frame_idx}/{total_frames}: {ffmpeg_err}")

                # Log progress every 5 seconds
                if frame_idx % (self.fps * 5) == 0:
                    progress = frame_idx / total_frames * 100
                    logger.info(f"  Rendering: {progress:.0f}% ({frame_time:.1f}s)")

                # Report to UI more frequently (e.g. every second)
                if progress_callback and frame_idx % self.fps == 0:
                    progress_callback(frame_idx / total_frames * 100)

            try:
                process.stdin.close()
            except (BrokenPipeError, ValueError, OSError):
                pass  # ffmpeg may have closed its end already

            try:
                stdout, stderr = process.communicate(timeout=300)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()

            # Clean up captures
            for cap in video_captures.values():
                cap.release()

            if process.returncode != 0:
                ffmpeg_err = stderr.decode(errors="replace")[-800:] if stderr else ""
                logger.error(f"FFmpeg error output: {ffmpeg_err}")
                raise RuntimeError(f"FFmpeg failed (code {process.returncode}): {ffmpeg_err}")

            logger.info(f"Video rendered: {output_path}")
            return str(output_file)

        except Exception as e:
            logger.error(f"Video rendering failed: {e}")
            if 'process' in locals():
                process.kill()
            raise

    def _render_frame(
        self,
        frame_time: float,
        total_duration: float,
        template: TemplateConfig,
        accent_color: tuple[int, int, int],
        script: GeneratedScript,
        sections: list[dict],
        caption_lines: list[CaptionLine],
        loaded_media: dict[str, Image.Image],
        video_captures: dict[str, cv2.VideoCapture],
        channel_name: str,
        source_text: str,
        show_progress_bar: bool,
        cta_text: str = "Get the daily AI briefing >>",
        cta_link: str = "bit.ly/neural-drop",
        cta_duration: float = 3.5,
        show_cta: bool = True,
    ) -> Image.Image:
        """Render a single video frame."""
        img = Image.new("RGB", (self.width, self.height))

        # 1. Background / B-Roll
        current_section = self._get_current_section(frame_time, sections)
        section_name = current_section["name"] if current_section else "hook"
        section_start = current_section["start"] if current_section else 0.0
        
        broll_img = None
        
        # Check if we have a video capture for this section
        cap = video_captures.get(section_name)
        if cap:
            # We want to match the video frame to the current frame_time relative to the section start
            # But the simplest way is just to grab the next frame if the video is playing
            ret, cv_frame = cap.read()
            if not ret:
                # Loop video if it ends early
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, cv_frame = cap.read()
            
            if ret:
                # Convert BGR (OpenCV) to RGB (Pillow)
                cv_frame = cv2.cvtColor(cv_frame, cv2.COLOR_BGR2RGB)
                broll_img = Image.fromarray(cv_frame)
        else:
            broll_img = loaded_media.get(section_name)
            
        if broll_img:
            # Ken Burns effect: scale from 1.0 to 1.15 over the section
            time_in_section = frame_time - section_start
            scale = 1.0 + (time_in_section * 0.015)  # Slow zoom
            
            img_w, img_h = broll_img.size
            
            # Target dimensions for video box (1440x810 for 16:9)
            box_w = self.width
            box_h = int(self.width * 9 / 16)
            
            # Target dimensions for resizing video to fill the box
            target_w = box_w
            target_h = int((img_h / img_w) * target_w)
            if target_h < box_h:
                target_h = box_h
                target_w = int((img_w / img_h) * target_h)
            
            # Apply Ken Burns scale
            curr_w = int(target_w * scale)
            curr_h = int(target_h * scale)
            
            resized = broll_img.resize((curr_w, curr_h), Image.Resampling.LANCZOS)
            
            # Center crop to box size
            left = (curr_w - box_w) // 2
            top = (curr_h - box_h) // 2
            cropped = resized.crop((left, top, left + box_w, top + box_h))
            
            # Tint overlay so it blends slightly (optional, but keeping it)
            overlay = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 80))
            box_img = Image.alpha_composite(cropped.convert("RGBA"), overlay).convert("RGB")
            
            # Draw black background for the whole canvas
            elem.draw_solid_background(img, (0, 0, 0))
            
            # Paste into center of canvas
            paste_y = (self.height - box_h) // 2
            img.paste(box_img, (0, paste_y))
        else:
            if template.use_gradient:
                elem.draw_gradient_background(img, template.bg_color_top, template.bg_color_bottom)
            else:
                elem.draw_solid_background(img, template.bg_color_top)

        # 2. Permanent Hook Text (Top)
        # Hook stays at top area above the video
        hook_y = int(self.height * 0.05)
        hook_opacity = anim.fade_in(frame_time, 0.0, duration=0.5)
        if hook_opacity > 0.05:
            elem.draw_text_centered(
                img, script.sections.hook.upper(), self._fonts["hook"], hook_y,
                color=accent_color, opacity=hook_opacity,
                max_width=self.width - 80,
            )
        
        # Accent line removed per user request

        # 5. Captions
        current_caption = self._get_current_caption(frame_time, caption_lines)
        if current_caption:
            # Captions locked to bottom 15%
            caption_y = int(self.height * 0.85)
            caption_opacity = anim.fade_in(
                frame_time, current_caption.start_time, duration=0.1
            ) * anim.fade_out(
                frame_time, current_caption.end_time, duration=0.1
            )

            if caption_opacity > 0.05:
                # Add a solid dark box behind captions for high contrast over any image
                # The text_overlay box is typically drawn inside draw_caption_text, 
                # but we'll ensure it's very clear here
                elem.draw_caption_text(
                    img,
                    text=current_caption.text,
                    font=self._fonts["caption"],
                    y=caption_y,
                    color=(255, 255, 255),
                    highlight_words=current_caption.highlighted_words,
                    accent_color=accent_color,
                    opacity=caption_opacity,
                )

        # 7. Watermark
        elem.draw_watermark(
            img,
            text=channel_name,
            font=self._fonts["watermark"],
            position="top_right",
            color=(60, 60, 80),
        )

        # 8. Progress bar
        if show_progress_bar:
            progress = anim.progress_bar_value(frame_time, total_duration)
            elem.draw_progress_bar(
                img,
                progress=progress,
                accent_color=accent_color,
                bar_height=4,
            )

        # 9. Persistent Neural Drop CTA Pill
        if show_cta:
            # Fade in quickly at the beginning, fade out at the very end
            pill_opacity = anim.fade_in(frame_time, 0.0, duration=0.5) * anim.fade_out(frame_time, total_duration - 0.5, duration=0.5)
            
            if pill_opacity > 0.05:
                pill_y = int(self.height * 0.75) # Just above the captions
                elem.draw_persistent_pill(
                    img,
                    cta_text=cta_text,
                    link_text=cta_link,
                    font=self._fonts["cta"],
                    accent_color=accent_color,
                    y_position=pill_y,
                    opacity=pill_opacity,
                )

        return img

    # _draw_section_text is no longer needed since we use visual b-roll and persistent hooks

    def _build_section_timeline(
        self, script: GeneratedScript, total_duration: float
    ) -> list[dict]:
        """Build a timeline of text sections from the script."""
        sections = []

        # Distribute time across sections
        # Hook: 0-2s, Explanation: 2-10s, Why it matters: 10-25s, Student angle + close: remaining
        hook_end = min(2.5, total_duration * 0.08)
        explain_end = min(12.0, total_duration * 0.35)
        why_end = min(28.0, total_duration * 0.70)
        angle_end = min(38.0, total_duration * 0.90)

        sections.append({
            "name": "hook",
            "text": script.sections.hook,
            "start": 0.0,
            "end": hook_end,
        })
        sections.append({
            "name": "explanation",
            "text": script.sections.main_explanation,
            "start": hook_end,
            "end": explain_end,
        })
        sections.append({
            "name": "why_it_matters",
            "text": script.sections.why_it_matters,
            "start": explain_end,
            "end": why_end,
        })
        sections.append({
            "name": "student_angle",
            "text": script.sections.student_dev_angle,
            "start": why_end,
            "end": angle_end,
        })
        sections.append({
            "name": "closing",
            "text": script.sections.closing_line,
            "start": angle_end,
            "end": total_duration,
        })

        return sections

    def _get_current_section(
        self, frame_time: float, sections: list[dict]
    ) -> Optional[dict]:
        """Get the section that should be displayed at the given time."""
        for section in sections:
            if section["start"] <= frame_time < section["end"]:
                return section
        return sections[-1] if sections else None

    def _get_current_caption(
        self, frame_time: float, caption_lines: list[CaptionLine]
    ) -> Optional[CaptionLine]:
        """Get the caption that should be displayed at the given time."""
        for caption in caption_lines:
            if caption.start_time <= frame_time <= caption.end_time:
                return caption
        return None

    def _build_ffmpeg_command(
        self, output_path: str, audio_path: str, duration: float
    ) -> list[str]:
        """Build the FFmpeg command for encoding."""
        return [
            "ffmpeg",
            "-y",  # Overwrite output
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{self.width}x{self.height}",
            "-pix_fmt", "rgb24",
            "-r", str(self.fps),
            "-i", "-",  # Pipe input
            "-i", audio_path,  # Audio input
            "-c:v", "libx264",
            "-preset", "faster",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",  # Match shortest stream
            "-movflags", "+faststart",
            output_path,
        ]

    def _get_font_path(self, style: str = "bold") -> str:
        """Get the best available font path."""
        candidates = [
            self.font_dir / "Inter" / f"Inter-{'Bold' if style == 'bold' else 'Regular'}.ttf",
            Path("/System/Library/Fonts/Helvetica.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ]
        for path in candidates:
            if path.exists():
                return str(path)
        return str(candidates[0])  # Will trigger fallback in get_font


def generate_thumbnail(
    output_path: str,
    template: TemplateConfig,
    accent_color: tuple[int, int, int],
    hook_text: str,
    channel_name: str = "TechPulse Shorts",
    width: int = 1080,
    height: int = 1920,
) -> str:
    """Generate a thumbnail / opening frame image."""
    img = Image.new("RGB", (width, height))

    # Background
    if template.use_gradient:
        elem.draw_gradient_background(img, template.bg_color_top, template.bg_color_bottom)
    else:
        elem.draw_solid_background(img, template.bg_color_top)

    # Glow
    if template.show_glow:
        elem.draw_glow(
            img, width // 2, int(height * 0.35),
            accent_color, radius=template.glow_radius, opacity=0.12,
        )

    # Card
    if template.show_card:
        elem.draw_card(
            img,
            y_start=int(height * 0.22),
            y_end=int(height * 0.62),
            accent_color=accent_color,
            opacity=template.card_opacity,
        )

    # Accent line
    if template.show_accent_line:
        elem.draw_accent_line(
            img, accent_color,
            y_position=int(height * (template.hook_y_ratio - 0.05)),
            line_width=template.accent_line_width,
        )

    # Hook text
    font_path = str(Path("./assets/fonts/Inter/Inter-Bold.ttf"))
    candidates = [
        font_path,
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for fp in candidates:
        if Path(fp).exists():
            font_path = fp
            break

    hook_font = elem.get_font(font_path, template.hook_font_size)
    elem.draw_text_centered(
        img, hook_text, hook_font,
        int(height * template.hook_y_ratio),
        color=accent_color,
        max_width=width - 80,
    )

    # Watermark
    watermark_font = elem.get_font(font_path, 18)
    elem.draw_watermark(img, channel_name, watermark_font)

    # Save
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_file), "PNG", quality=95)
    logger.info(f"Thumbnail saved: {output_path}")
    return str(output_file)
