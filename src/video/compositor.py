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
        # Anton is used for captions (Impact-style heavy font)
        self._anton_path = str(self.font_dir / "Anton" / "Anton-Regular.ttf")

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

        # On CI (GitHub Actions) render at 10fps to cut wall time by 3x.
        # Output is re-stamped to 30fps by FFmpeg so playback is smooth.
        import os
        render_fps = 5 if os.getenv("CI") else self.fps
        total_frames = int(total_duration * render_fps)
        logger.info(
            f"Rendering {total_frames} frames ({total_duration:.1f}s) at {render_fps}fps"
            + (" [CI fast mode]" if render_fps != self.fps else "")
        )

        # Pre-load media images and video captures into memory
        loaded_media = {}
        video_captures = {}
        IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
        VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv"}
        for section, path in media_paths.items():
            ext = Path(path).suffix.lower()
            if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
                continue  # skip .vtt, .mp3, .srt etc.
            if Path(path).exists():
                try:
                    if ext in VIDEO_EXTS:
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
        # Use Anton (Impact-style) for captions if available, else fall back to bold
        caption_font_path = self._anton_path if Path(self._anton_path).exists() else self._get_font_path("bold")
        self._fonts["caption"] = elem.get_font(caption_font_path, template.caption_font_size)

        # Build section timeline
        sections = self._build_section_timeline(script, total_duration)

        # Start FFmpeg process
        ffmpeg_cmd = self._build_ffmpeg_command(output_path, audio_path, total_duration, render_fps)

        try:
            process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            for frame_idx in range(total_frames):
                frame_time = frame_idx / render_fps

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
                if frame_idx % (render_fps * 5) == 0:
                    progress = frame_idx / total_frames * 100
                    logger.info(f"  Rendering: {progress:.0f}% ({frame_time:.1f}s)")

                # Report to UI more frequently (e.g. every second)
                if progress_callback and frame_idx % render_fps == 0:
                    progress_callback(frame_idx / total_frames * 100)

            try:
                process.stdin.close()
            except (BrokenPipeError, ValueError, OSError):
                pass
            finally:
                process.stdin = None  # always clear — communicate() flushes stdin if not None

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

        # Try every section name in fallback order: current → all others → motion bg
        _candidates = [section_name] + [s for s in list(video_captures.keys()) + list(loaded_media.keys()) if s != section_name]
        for _candidate in _candidates:
            cap = video_captures.get(_candidate)
            if cap:
                ret, cv_frame = cap.read()
                if not ret:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, cv_frame = cap.read()
                if ret:
                    cv_frame = cv2.cvtColor(cv_frame, cv2.COLOR_BGR2RGB)
                    broll_img = Image.fromarray(cv_frame)
                    break
            else:
                still = loaded_media.get(_candidate)
                if still:
                    broll_img = still
                    break
            
        if broll_img:
            # Ken Burns: zoom in noticeably over each section (resets at section start)
            time_in_section = frame_time - section_start
            scale = 1.0 + (time_in_section * 0.035)  # ~3.5% zoom per second — clearly visible

            img_w, img_h = broll_img.size
            aspect = img_w / img_h if img_h > 0 else 1.0

            # Always fill the FULL 9:16 canvas — no black bars
            if aspect >= 1.0:
                # Landscape/square → scale to fill height, crop sides
                target_h = self.height
                target_w = int(img_w / img_h * target_h)
                if target_w < self.width:
                    target_w = self.width
                    target_h = int(img_h / img_w * target_w)
            else:
                # Portrait → scale to fill width
                target_w = self.width
                target_h = int(img_h / img_w * target_w)
                if target_h < self.height:
                    target_h = self.height
                    target_w = int(img_w / img_h * target_h)

            curr_w = max(self.width, int(target_w * scale))
            curr_h = max(self.height, int(target_h * scale))

            resized = broll_img.resize((curr_w, curr_h), Image.Resampling.LANCZOS)

            # Center-crop to exact canvas size
            left = (curr_w - self.width) // 2
            top = (curr_h - self.height) // 2
            cropped = resized.crop((left, top, left + self.width, top + self.height))

            # Dark gradient overlay so text stays readable over any footage
            overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
            from PIL import ImageDraw as _ID
            _d = _ID.Draw(overlay)
            # Top gradient (hook text zone)
            for y in range(300):
                alpha = int(180 * (1 - y / 300))
                _d.line([(0, y), (self.width, y)], fill=(0, 0, 0, alpha))
            # Bottom gradient (caption zone)
            for y in range(400):
                alpha = int(190 * (1 - y / 400))
                _d.line([(0, self.height - 1 - y), (self.width, self.height - 1 - y)], fill=(0, 0, 0, alpha))

            img = Image.alpha_composite(cropped.convert("RGBA"), overlay).convert("RGB")

        else:
            # No b-roll — render an animated motion-graphics background so the
            # frame is never a plain empty color.
            self._draw_motion_background(img, frame_time, accent_color, template)

        # Hook text — persistent white stroke label at top, always visible
        hook_opacity = anim.fade_in(frame_time, 0.0, duration=0.3)
        if hook_opacity > 0.05:
            self._draw_hook_badge(img, script.sections.hook, self._fonts["hook"], hook_opacity, accent_color)

        # 5. Captions — CapCut style: centered, large, karaoke word highlight
        current_caption = self._get_current_caption(frame_time, caption_lines)
        if current_caption:
            caption_opacity = anim.fade_in(
                frame_time, current_caption.start_time, duration=0.06
            ) * anim.fade_out(
                frame_time, current_caption.end_time, duration=0.06
            )
            if caption_opacity > 0.05:
                active_word: str | None = None
                if current_caption.words:
                    for wt in current_caption.words:
                        if wt.start <= frame_time <= wt.end:
                            active_word = wt.word.strip(".,!?;:").lower()
                            break
                    if active_word is None:
                        upcoming = [w for w in current_caption.words if w.start > frame_time]
                        if upcoming:
                            active_word = upcoming[0].word.strip(".,!?;:").lower()

                self._draw_karaoke_caption(
                    img, current_caption.text, self._fonts["caption"],
                    active_word=active_word,
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
        """Build a timeline using the script's visual_plan section names so they
        match exactly the keys in media_paths / video_captures."""
        sections = []

        if script.visual_plan:
            text_map = {
                "hook": script.sections.hook,
                "main_explanation": script.sections.main_explanation,
                "why_it_matters": script.sections.why_it_matters,
                "student_dev_angle": script.sections.student_dev_angle,
                "closing_line": script.sections.closing_line,
            }
            # Hook always gets exactly 5 seconds; remaining time split by hints
            HOOK_DURATION = 5.0
            non_hook = [cue for cue in script.visual_plan if cue.section != "hook"]
            remaining = max(0.0, total_duration - HOOK_DURATION)
            hint_sum = sum(cue.duration_hint or 8.0 for cue in non_hook) or 1.0

            cursor = 0.0
            for cue in script.visual_plan:
                if cue.section == "hook":
                    end = HOOK_DURATION
                else:
                    frac = (cue.duration_hint or 8.0) / hint_sum
                    end = cursor + remaining * frac
                sections.append({
                    "name": cue.section,
                    "text": text_map.get(cue.section, cue.text_overlay or ""),
                    "start": round(cursor, 3),
                    "end": round(end, 3),
                })
                cursor = end
            if sections:
                sections[-1]["end"] = total_duration
        else:
            # Fallback: evenly split five hardcoded sections
            t = total_duration / 5
            for i, (name, field) in enumerate([
                ("hook", script.sections.hook),
                ("main_explanation", script.sections.main_explanation),
                ("why_it_matters", script.sections.why_it_matters),
                ("student_dev_angle", script.sections.student_dev_angle),
                ("closing_line", script.sections.closing_line),
            ]):
                sections.append({"name": name, "text": field,
                                  "start": round(i * t, 3), "end": round((i + 1) * t, 3)})
            if sections:
                sections[-1]["end"] = total_duration

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

    def _draw_hook_badge(
        self,
        img: Image.Image,
        hook_text: str,
        font,
        opacity: float,
        accent_color: tuple,
    ) -> None:
        """Hook text at top — wraps to fit width, white with black stroke."""
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        w, h = img.size
        stroke = 5
        max_w = w - 240  # narrower → shorter lines, more wrapping
        # Take first complete sentence if possible, otherwise first 8 words
        import re as _re
        first_sentence = _re.split(r'(?<=[.!?])\s', hook_text.strip())
        hook_short = first_sentence[0] if first_sentence and len(first_sentence[0].split()) <= 12 else hook_text
        words = hook_short.upper().split()[:12]

        # Greedy word-wrap into lines that fit max_w
        lines, line = [], []
        for word in words:
            test = " ".join(line + [word])
            bb = font.getbbox(test)
            if bb[2] - bb[0] > max_w and line:
                lines.append(" ".join(line))
                line = [word]
            else:
                line.append(word)
        if line:
            lines.append(" ".join(line))

        line_h = font.getbbox("A")[3] + 6
        total_h = len(lines) * line_h
        # Anchor bottom of hook text block at y=560, grow upward
        bottom_y = 560
        y = bottom_y - total_h
        for text in lines:
            bb = font.getbbox(text)
            lx = (w - (bb[2] - bb[0])) // 2
            for dx in range(-stroke, stroke + 1):
                for dy in range(-stroke, stroke + 1):
                    if abs(dx) + abs(dy) <= stroke + 1 and not (dx == 0 and dy == 0):
                        draw.text((lx + dx, y + dy), text, fill=(0, 0, 0), font=font)
            draw.text((lx, y), text, fill=(255, 255, 255), font=font)
            y += line_h

    def _draw_motion_background(
        self,
        img: Image.Image,
        frame_time: float,
        accent_color: tuple,
        template,
    ) -> None:
        """Animated motion-graphics background — used when no b-roll is available.

        Renders a dark gradient base with slowly drifting orbs/blobs in the
        accent color so the frame is always visually interesting.
        """
        import math
        from PIL import ImageDraw, ImageFilter

        w, h = img.size
        draw = ImageDraw.Draw(img)

        # 1. Dark base gradient (top to bottom: near-black → very dark accent tint)
        r, g, b = accent_color
        for y in range(h):
            t = y / h
            cr = int(8  + t * max(0, r // 8))
            cg = int(8  + t * max(0, g // 8))
            cb = int(18 + t * max(0, b // 8))
            draw.line([(0, y), (w, y)], fill=(cr, cg, cb))

        # 2. Floating orbs — 5 blobs that drift slowly
        orb_params = [
            (0.25, 0.30, 0.55, 0.7, 260),
            (0.72, 0.55, 0.40, 0.9, 200),
            (0.50, 0.70, 0.60, 0.5, 320),
            (0.15, 0.75, 0.45, 0.6, 180),
            (0.80, 0.20, 0.50, 0.8, 240),
        ]
        orb_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        od = ImageDraw.Draw(orb_layer)
        for i, (bx, by, spd, amp, rad) in enumerate(orb_params):
            phase = i * 1.3
            cx = int((bx + math.sin(frame_time * spd + phase) * 0.10 * amp / 100) * w)
            cy = int((by + math.cos(frame_time * spd * 0.7 + phase) * 0.08 * amp / 100) * h)
            # Draw a soft orb by stacking semi-transparent ellipses
            for layer_r in range(rad, 0, -20):
                alpha = int(18 * (1 - layer_r / rad))
                od.ellipse(
                    [cx - layer_r, cy - layer_r, cx + layer_r, cy + layer_r],
                    fill=(r, g, b, alpha),
                )

        blurred_orbs = orb_layer.filter(ImageFilter.GaussianBlur(radius=40))
        img.paste(Image.alpha_composite(img.convert("RGBA"), blurred_orbs).convert("RGB"))

        # 3. Subtle grid lines for a "data / tech" feel
        draw2 = ImageDraw.Draw(img)
        grid_alpha = 18
        grid_spacing = 120
        for gx in range(0, w, grid_spacing):
            draw2.line([(gx, 0), (gx, h)], fill=(r // 4, g // 4, b // 4 + 10))
        for gy in range(0, h, grid_spacing):
            draw2.line([(0, gy), (w, gy)], fill=(r // 4, g // 4, b // 4 + 10))

        # 4. Vignette — darken edges so center is the focal point
        vig = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        vd = ImageDraw.Draw(vig)
        steps = 80
        for s in range(steps):
            margin = int(s * min(w, h) / (steps * 2))
            alpha = int(160 * (1 - s / steps) ** 2)
            vd.rectangle([margin, margin, w - margin, h - margin], outline=(0, 0, 0, alpha), width=1)
        img.paste(Image.alpha_composite(img.convert("RGBA"), vig).convert("RGB"))

    def _draw_karaoke_caption(
        self,
        img: Image.Image,
        text: str,
        font,
        active_word: str | None,
        accent_color: tuple,
        opacity: float = 1.0,
    ) -> None:
        """TikTok-style captions: bold white text, thick black stroke, yellow active word."""
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        width, height = img.size
        words = text.upper().split()
        if not words:
            return

        def word_w(w: str) -> int:
            bb = font.getbbox(w)
            return bb[2] - bb[0]

        space_w = word_w(" ")
        total_w = sum(word_w(w) for w in words) + space_w * (len(words) - 1)

        # Break into 2 lines only if truly needed
        max_w = width - 80
        if total_w > max_w:
            mid = len(words) // 2
            lines = [words[:mid], words[mid:]]
        else:
            lines = [words]

        line_h = font.getbbox("A")[3] + 12
        total_lines_h = len(lines) * line_h
        base_y = int(height * 0.72) - total_lines_h // 2

        stroke = 6  # thick black outline like TikTok

        for line_idx, line_words in enumerate(lines):
            line_text_w = sum(word_w(w) for w in line_words) + space_w * (len(line_words) - 1)
            cur_x = (width - line_text_w) // 2
            cur_y = base_y + line_idx * line_h

            for i, word in enumerate(line_words):
                # Compare against active_word (already lowercased strip from caller)
                clean_lower = word.lower().strip(".,!?;:'\"")
                is_active = bool(active_word) and clean_lower == active_word

                fill_color = (255, 220, 0) if is_active else (255, 255, 255)

                # Thick black stroke: draw text offset in a ring
                for dx in range(-stroke, stroke + 1):
                    for dy in range(-stroke, stroke + 1):
                        if dx == 0 and dy == 0:
                            continue
                        if abs(dx) + abs(dy) <= stroke + 1:
                            draw.text(
                                (cur_x + dx, cur_y + dy),
                                word,
                                fill=(0, 0, 0),
                                font=font,
                            )

                # Draw white (or yellow) fill on top
                draw.text((cur_x, cur_y), word, fill=fill_color, font=font)

                cur_x += word_w(word) + (space_w if i < len(line_words) - 1 else 0)

    def _build_ffmpeg_command(
        self, output_path: str, audio_path: str, duration: float, render_fps: int = None
    ) -> list[str]:
        """Build the FFmpeg command for encoding."""
        import os
        in_fps = render_fps or self.fps
        preset = "ultrafast" if os.getenv("CI") else "faster"
        return [
            "ffmpeg",
            "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{self.width}x{self.height}",
            "-pix_fmt", "rgb24",
            "-r", str(in_fps),   # input frame rate (10fps on CI)
            "-i", "-",
            "-i", audio_path,
            "-c:v", "libx264",
            "-profile:v", "baseline",
            "-level", "3.1",
            "-preset", preset,
            "-crf", "23",
            "-r", str(self.fps), # output frame rate always 30fps
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
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
