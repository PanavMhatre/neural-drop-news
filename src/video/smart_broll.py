import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import requests
import webvtt
import yt_dlp
from pydantic import BaseModel, Field

from src.models.schemas import GeneratedScript, RawStory, VisualCue
from src.video.engagement_crop import engagement_window_start

logger = logging.getLogger(__name__)

PIXABAY_API_URL = "https://pixabay.com/api/videos/"

# Maps crypto story keywords to good Pixabay search terms
CRYPTO_PIXABAY_KEYWORDS = {
    "bitcoin": "bitcoin cryptocurrency",
    "ethereum": "ethereum blockchain",
    "solana": "cryptocurrency blockchain",
    "defi": "blockchain finance",
    "regulation": "government finance law",
    "etf": "stock market finance",
    "exchange": "cryptocurrency trading",
    "hack": "cybersecurity hacker",
    "mining": "cryptocurrency mining",
    "stablecoin": "digital currency finance",
    "institutional": "finance investment",
    "treasury": "finance investment",
}


class TimestampMatch(BaseModel):
    start_time: float = Field(description="Start time in seconds")
    end_time: float = Field(description="End time in seconds")


class SmartBRollAgent:
    """Acquires video b-roll: YouTube (with cookies) → Pixabay stock video. Never a static graphic."""

    def __init__(self, output_dir: str, openai_client):
        self.output_dir = Path(output_dir) / "media"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.font_dir = Path("./assets/fonts/Montserrat")
        self.client = openai_client
        self.cookies_file = os.getenv("YOUTUBE_COOKIES_FILE", "")
        self.pixabay_api_key = os.getenv("PIXABAY_API_KEY", "")

        import yaml
        try:
            with open("config.yaml") as f:
                config = yaml.safe_load(f)
            self.model = config.get("models", {}).get("cheap", "gpt-4o-mini")
        except Exception:
            self.model = "gpt-4o-mini"

    def _ydl_opts(self, extra: dict | None = None) -> dict:
        opts = {
            "format": "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": str(self.output_dir / "source_video.%(ext)s"),
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en"],
            "subtitlesformat": "vtt",
            "noplaylist": True,
            "quiet": True,
        }
        if self.cookies_file and Path(self.cookies_file).exists():
            opts["cookiefile"] = self.cookies_file
            logger.info("Using YouTube cookies file for yt-dlp")
        if extra:
            opts.update(extra)
        return opts

    def acquire_media(self, script: GeneratedScript, story: RawStory, accent_color: tuple[int, int, int]) -> dict[str, str]:
        media_paths = {}

        # 1. Try YouTube (direct article URL, then keyword search)
        video_path, subs_path = self._download_youtube(story.url, story.title)
        transcript = self._parse_subtitles(subs_path) if subs_path else []

        for i, cue in enumerate(script.visual_plan):
            section = cue.section
            out_path = self.output_dir / f"{section}.mp4"

            # Try trimming from YouTube video
            if video_path and Path(video_path).exists():
                start_t, end_t = self._find_best_segment(cue, transcript, default_start=i * 10.0)
                if self._trim_video(video_path, str(out_path), start_t, end_t):
                    media_paths[section] = str(out_path)
                    continue

            # Fallback: Pixabay stock video
            pixabay_path = self._fetch_pixabay_video(story.title, section, i)
            if pixabay_path:
                media_paths[section] = pixabay_path
                continue

            # Absolute last resort: black video (never a static PNG)
            logger.error(f"All video sources failed for section '{section}' — using black video")
            media_paths[section] = self._make_blank_video(str(out_path))

        return media_paths

    # ── YouTube ───────────────────────────────────────────────────────────────

    def _download_youtube(self, url: str, title: str) -> tuple[Optional[str], Optional[str]]:
        if not url or url.startswith("mock://"):
            return self._youtube_search(title)

        if url.startswith("file://"):
            import shutil
            local_path = url[7:]
            if Path(local_path).exists():
                ext = Path(local_path).suffix.lstrip(".") or "mp4"
                dest = self.output_dir / f"source_video.{ext}"
                shutil.copy2(local_path, dest)
                return str(dest), None
            return self._youtube_search(title)

        logger.info(f"Downloading video from article URL: {url}")
        try:
            with yt_dlp.YoutubeDL(self._ydl_opts()) as ydl:
                info = ydl.extract_info(url, download=True)
                ext = info.get("ext", "mp4")
                video_path = self.output_dir / f"source_video.{ext}"
                subs_path = next(self.output_dir.glob("source_video.*.vtt"), None)
                if video_path.exists():
                    logger.info("Direct article video downloaded successfully")
                    return str(video_path), str(subs_path) if subs_path else None
        except Exception as e:
            logger.warning(f"Direct URL download failed: {e}")

        return self._youtube_search(title)

    def _youtube_search(self, title: str) -> tuple[Optional[str], Optional[str]]:
        search_query = f"ytsearch1:{title} news"
        logger.info(f"YouTube search: {search_query}")
        try:
            with yt_dlp.YoutubeDL(self._ydl_opts()) as ydl:
                info = ydl.extract_info(search_query, download=True)
                entries = info.get("entries") or [info]
                ext = entries[0].get("ext", "mp4") if entries else "mp4"
                video_path = self.output_dir / f"source_video.{ext}"
                subs_path = next(self.output_dir.glob("source_video.*.vtt"), None)
                if video_path.exists():
                    logger.info("YouTube search video downloaded successfully")
                    return str(video_path), str(subs_path) if subs_path else None
        except Exception as e:
            logger.warning(f"YouTube search failed: {e}")
        return None, None

    # ── Pixabay ───────────────────────────────────────────────────────────────

    def _pixabay_search_terms(self, story_title: str) -> str:
        title_lower = story_title.lower()
        for keyword, search_term in CRYPTO_PIXABAY_KEYWORDS.items():
            if keyword in title_lower:
                return search_term
        return "cryptocurrency blockchain finance"

    def _fetch_pixabay_video(self, story_title: str, section: str, index: int) -> Optional[str]:
        if not self.pixabay_api_key:
            logger.warning("No PIXABAY_API_KEY set — skipping Pixabay fallback")
            return None

        search_term = self._pixabay_search_terms(story_title)
        logger.info(f"Pixabay fallback for '{section}': query='{search_term}'")

        try:
            resp = requests.get(
                PIXABAY_API_URL,
                params={
                    "key": self.pixabay_api_key,
                    "q": search_term,
                    "video_type": "film",
                    "per_page": 10,
                    "safesearch": "true",
                },
                timeout=15,
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
            if not hits:
                logger.warning(f"Pixabay returned no results for '{search_term}'")
                return None

            # Vary clips per section so they don't all look the same
            hit = hits[index % len(hits)]
            videos = hit.get("videos", {})
            video_info = (
                videos.get("medium")
                or videos.get("small")
                or videos.get("large")
                or videos.get("tiny")
            )
            if not video_info:
                return None

            out_path = self.output_dir / f"{section}_pixabay.mp4"
            dl_resp = requests.get(video_info["url"], timeout=60, stream=True)
            dl_resp.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in dl_resp.iter_content(chunk_size=1 << 16):
                    f.write(chunk)

            if out_path.exists() and out_path.stat().st_size > 10_000:
                logger.info(f"Pixabay video saved: {out_path}")
                return str(out_path)

        except Exception as e:
            logger.warning(f"Pixabay fetch failed: {e}")

        return None

    # ── Utilities ──────────────────────────────────────────────────────────────

    def _make_blank_video(self, output_path: str, duration: float = 10.0) -> str:
        """Black video loop — absolute last resort so we always have a video, never a PNG."""
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=black:size=1080x1920:duration={duration}:rate=30",
            "-c:v", "libx264", "-preset", "ultrafast",
            output_path,
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return output_path

    def _parse_subtitles(self, subs_path: str) -> list[dict]:
        try:
            subs = webvtt.read(subs_path)
            return [
                {"start": cap.start_in_seconds, "end": cap.end_in_seconds, "text": cap.text.replace("\n", " ")}
                for cap in subs
            ]
        except Exception as e:
            logger.warning(f"Failed to parse VTT: {e}")
            return []

    def _find_best_segment(self, cue: VisualCue, transcript: list[dict], default_start: float = 0.0) -> tuple[float, float]:
        target_duration = cue.duration_hint or 8.0
        if not transcript:
            return default_start, default_start + target_duration

        lines = [f"[{t['start']:.1f} - {t['end']:.1f}] {t['text']}" for t in transcript[:300]]
        try:
            response = self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an AI video editor. Find the best video segment that matches the visual cue."},
                    {"role": "user", "content": (
                        f"Visual Cue: {cue.description}\nText Overlay: {cue.text_overlay}\n\n"
                        f"Transcript:\n" + "\n".join(lines) + f"\n\nFind ~{target_duration}s segment. "
                        'Respond ONLY with JSON: {"start_time": float, "end_time": float}'
                    )},
                ],
                response_format=TimestampMatch,
                temperature=0.0,
            )
            match = response.choices[0].message.parsed
            if match.end_time - match.start_time < 3.0:
                match.end_time = match.start_time + target_duration
            return match.start_time, match.end_time
        except Exception as e:
            logger.warning(f"ML timestamp matching failed: {e}")
            return default_start, default_start + target_duration

    def _trim_video(self, input_path: str, output_path: str, start_t: float, end_t: float) -> bool:
        if start_t <= 0:
            duration = max(3.0, end_t - start_t)
            start_t = engagement_window_start(input_path, duration=duration)
            end_t = start_t + duration
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_t), "-to", str(end_t),
            "-i", input_path,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-an",
            output_path,
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return Path(output_path).exists()
        except subprocess.CalledProcessError:
            return False
