import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import webvtt
import yt_dlp
from pydantic import BaseModel, Field

from src.models.schemas import GeneratedScript, RawStory, VisualCue
from src.video.engagement_crop import engagement_window_start

logger = logging.getLogger(__name__)

class TimestampMatch(BaseModel):
    start_time: float = Field(description="Start time in seconds")
    end_time: float = Field(description="End time in seconds")

class SmartBRollAgent:
    """Acquires video b-roll using yt-dlp and ML timestamp matching."""

    def __init__(self, output_dir: str, openai_client):
        self.output_dir = Path(output_dir) / "media"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.font_dir = Path("./assets/fonts/Montserrat")
        
        self.client = openai_client
        import yaml
        try:
            with open("config.yaml") as f:
                config = yaml.safe_load(f)
            self.model = config.get("models", {}).get("cheap", "gpt-4o-mini")
        except:
            self.model = "gpt-4o-mini"

    def acquire_media(self, script: GeneratedScript, story: RawStory, accent_color: tuple[int, int, int]) -> dict[str, str]:
        """
        Acquires video clips for each section.
        Returns a dict mapping section name to video/image path.
        """
        media_paths = {}
        
        # 1. Download source video and subs using yt-dlp
        video_path, subs_path = self._download_source_video(story.url, story.title)
        
        # 2. Extract transcript if subs exist
        transcript = self._parse_subtitles(subs_path) if subs_path else []
        
        # 3. For each cue, trim the video or fallback to image
        for i, cue in enumerate(script.visual_plan):
            section = cue.section
            out_path = self.output_dir / f"{section}.mp4"
            
            if video_path and Path(video_path).exists():
                # Try to ML match
                start_t, end_t = self._find_best_segment(cue, transcript, default_start=i*10.0)
                
                # Trim video
                success = self._trim_video(video_path, str(out_path), start_t, end_t)
                if success:
                    media_paths[section] = str(out_path)
                    continue
            
            # Fallback to generated image if video fails or doesn't exist
            fallback_path = self.output_dir / f"{section}.png"
            self._generate_headline_graphic(str(fallback_path), cue.text_overlay or cue.description, story.source_name, accent_color)
            media_paths[section] = str(fallback_path)
            
        return media_paths

    def _download_source_video(self, url: str, title: str) -> tuple[Optional[str], Optional[str]]:
        """Downloads the best video and auto-subs using yt-dlp, or copies local file."""
        if not url or url.startswith("mock://"):
            return None, None
            
        logger.info(f"Attempting to download video from {url}")
        
        # Handle local file uploads from Render Studio
        if url.startswith("file://"):
            import shutil
            local_path = url[7:] # remove file://
            if Path(local_path).exists():
                ext = Path(local_path).suffix.lstrip('.') or 'mp4'
                video_path = self.output_dir / f"source_video.{ext}"
                shutil.copy2(local_path, video_path)
                logger.info(f"Copied local file from {local_path}")
                return str(video_path), None
            else:
                logger.warning(f"Local file not found: {local_path}")
                return None, None
        
        ydl_opts = {
            'format': 'bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': str(self.output_dir / 'source_video.%(ext)s'),
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['en'],
            'subtitlesformat': 'vtt',
            'noplaylist': True,
            'quiet': True,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                ext = info.get('ext', 'mp4')
                video_path = self.output_dir / f"source_video.{ext}"
                
                subs_path = next(self.output_dir.glob("source_video.*.vtt"), None)
                if video_path.exists():
                    logger.info("Video downloaded successfully.")
                    return str(video_path), str(subs_path) if subs_path else None
        except Exception as e:
            logger.warning(f"yt-dlp failed to download from direct URL: {e}. Falling back to ytsearch.")
            
        # Fallback to YouTube search for the topic title
        try:
            search_query = f"ytsearch1:{title}"
            logger.info(f"Searching YouTube for official video: {search_query}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search_query, download=True)
                # ytsearch returns a dict with 'entries'
                if 'entries' in info and len(info['entries']) > 0:
                    ext = info['entries'][0].get('ext', 'mp4')
                else:
                    ext = info.get('ext', 'mp4')
                video_path = self.output_dir / f"source_video.{ext}"
                
                subs_path = next(self.output_dir.glob("source_video.*.vtt"), None)
                if video_path.exists():
                    logger.info("Fallback YouTube video downloaded successfully.")
                    return str(video_path), str(subs_path) if subs_path else None
        except Exception as e:
            logger.warning(f"yt-dlp ytsearch fallback failed: {e}")
            
        return None, None

    def _parse_subtitles(self, subs_path: str) -> list[dict]:
        """Parses VTT file into list of dicts with text, start, end."""
        try:
            subs = webvtt.read(subs_path)
            transcript = []
            for cap in subs:
                transcript.append({
                    "start": cap.start_in_seconds,
                    "end": cap.end_in_seconds,
                    "text": cap.text.replace('\n', ' ')
                })
            return transcript
        except Exception as e:
            logger.warning(f"Failed to parse VTT: {e}")
            return []

    def _find_best_segment(self, cue: VisualCue, transcript: list[dict], default_start: float = 0.0) -> tuple[float, float]:
        """Uses LLM to match cue description to transcript timestamps."""
        # Need at least 5 seconds of b-roll
        target_duration = cue.duration_hint or 8.0
        
        if not transcript:
            return default_start, default_start + target_duration
            
        # Create a compressed transcript text for the LLM
        # If it's too long, we might just take the first 5 mins
        lines = []
        for t in transcript[:300]: # limit to ~10 mins
            lines.append(f"[{t['start']:.1f} - {t['end']:.1f}] {t['text']}")
            
        transcript_text = "\n".join(lines)
        
        system_prompt = "You are an AI video editor. Find the best video segment that matches the visual cue."
        user_prompt = f"""
We need a b-roll clip for a news video.
Visual Cue Description: {cue.description}
Text Overlay: {cue.text_overlay}

Here is the transcript of the source video:
{transcript_text}

Analyze the transcript and find the exact timestamps that best match the Visual Cue. The segment should be around {target_duration} seconds long.
Respond ONLY with a JSON object: {{"start_time": float, "end_time": float}}
"""
        
        try:
            response = self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format=TimestampMatch,
                temperature=0.0
            )
            match = response.choices[0].message.parsed
            
            # Ensure duration is at least 3 seconds
            if match.end_time - match.start_time < 3.0:
                match.end_time = match.start_time + target_duration
                
            return match.start_time, match.end_time
            
        except Exception as e:
            logger.warning(f"ML matching failed: {e}. Using default.")
            return default_start, default_start + target_duration

    def _trim_video(self, input_path: str, output_path: str, start_t: float, end_t: float) -> bool:
        """Trims video using FFmpeg."""
        if start_t <= 0:
            duration = max(3.0, end_t - start_t)
            start_t = engagement_window_start(input_path, duration=duration)
            end_t = start_t + duration
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_t),
            "-to", str(end_t),
            "-i", input_path,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-an", # No audio needed for b-roll
            output_path
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return Path(output_path).exists()
        except subprocess.CalledProcessError:
            return False

    def _generate_headline_graphic(self, output_path: str, text: str, source_name: str, accent_color: tuple[int, int, int]) -> None:
        """Fallback generated image."""
        from PIL import Image, ImageDraw
        from src.video import elements as elem
        
        width, height = 1440, 1440
        img = Image.new("RGB", (width, height), (15, 23, 42)) 
        elem.draw_glow(img, width//2, height//2, accent_color, radius=600, opacity=0.15)
        
        draw = ImageDraw.Draw(img, "RGBA")
        card_w, card_h = 880, 600
        card_x = (width - card_w) // 2
        card_y = (height - card_h) // 2
        
        draw.rounded_rectangle([card_x-10, card_y-10, card_x+card_w+10, card_y+card_h+10], radius=32, fill=(0,0,0,100))
        draw.rounded_rectangle([card_x, card_y, card_x+card_w, card_y+card_h], radius=24, fill=(30, 41, 59, 230), outline=accent_color, width=2)
        
        font_path = str(self.font_dir / "Montserrat-Bold.ttf")
        if not Path(font_path).exists():
            font_path = "/System/Library/Fonts/Helvetica.ttc"
            
        source_font = elem.get_font(font_path, 28)
        draw.text((card_x + 40, card_y + 40), str(source_name).upper(), font=source_font, fill=accent_color)
        
        headline_font = elem.get_font(font_path, 56)
        elem.draw_text_centered(img, text, headline_font, card_y + 250, color=(248, 250, 252), max_width=card_w - 80)
        
        img.save(output_path, "PNG", quality=95)
