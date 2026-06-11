import logging
import os
import subprocess
import time
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
YOUTUBE_SEARCH_API = "https://www.googleapis.com/youtube/v3/search"
# Standard yt-dlp cookie location written by the workflow
YTDLP_COOKIE_PATH = str(Path.home() / ".config/yt-dlp/cookies.txt")

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


class NoVideoAvailable(Exception):
    """Raised when no video source could be acquired for a story — pipeline should skip it."""


class TimestampMatch(BaseModel):
    start_time: float = Field(description="Start time in seconds")
    end_time: float = Field(description="End time in seconds")


class SmartBRollAgent:
    """
    Video acquisition priority:
      1. YouTube search with cookies → clip relevant segment
      2. Pixabay stock video matched to story keywords
      3. Raise NoVideoAvailable — pipeline skips story, never renders garbage
    """

    def __init__(self, output_dir: str, openai_client):
        self.output_dir = Path(output_dir) / "media"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.client = openai_client
        self.pixabay_api_key = os.getenv("PIXABAY_API_KEY", "")
        self.youtube_api_key = os.getenv("YOUTUBE_API_KEY", "")

        # Cookie file: env override or standard yt-dlp location written by workflow
        cookie_env = os.getenv("YOUTUBE_COOKIES_FILE", "")
        self.cookies_file = cookie_env if cookie_env else YTDLP_COOKIE_PATH

        import yaml
        try:
            with open("config.yaml") as f:
                config = yaml.safe_load(f)
            self.model = config.get("models", {}).get("cheap", "gpt-4o-mini")
        except Exception:
            self.model = "gpt-4o-mini"

    def _ydl_opts(self, outtmpl: str | None = None) -> dict:
        # Python yt_dlp library does NOT read ~/.config/yt-dlp/config — must pass explicitly
        cookie_path = Path(self.cookies_file) if self.cookies_file else Path.home() / ".config/yt-dlp/cookies.txt"
        if cookie_path.exists():
            logger.info(f"yt-dlp cookies: {cookie_path} ({cookie_path.stat().st_size} bytes)")
        else:
            logger.warning(f"No yt-dlp cookie file at {cookie_path} — YouTube may block downloads")
            cookie_path = None

        opts = {
            "format": "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": outtmpl or str(self.output_dir / "source_video.%(ext)s"),
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en"],
            "subtitlesformat": "vtt",
            "noplaylist": True,
            "quiet": False,
            "no_warnings": False,
            "sleep_interval_requests": 2,
            "sleep_interval": 3,
            "max_sleep_interval": 8,
            "retries": 5,
            # ios client bypasses bot detection from CI IPs
            "extractor_args": {"youtube": {"player_client": ["ios"]}},
        }
        if cookie_path:
            opts["cookiefile"] = str(cookie_path)
        return opts

    def acquire_media(self, script: GeneratedScript, story: RawStory, accent_color: tuple) -> dict[str, str]:
        media_paths = {}

        # 1. Try YouTube
        video_path, subs_path = self._download_youtube(story.url, story.title)
        transcript = self._parse_subtitles(subs_path) if subs_path else []

        for i, cue in enumerate(script.visual_plan):
            section = cue.section
            out_path = self.output_dir / f"{section}.mp4"

            if video_path and Path(video_path).exists():
                start_t, end_t = self._find_best_segment(cue, transcript, default_start=i * 10.0)
                if self._trim_video(video_path, str(out_path), start_t, end_t):
                    media_paths[section] = str(out_path)
                    continue

            # 2. Pixabay fallback
            pixabay_path = self._fetch_pixabay_video(story.title, section, i)
            if pixabay_path:
                media_paths[section] = pixabay_path
                continue

            # 3. No video — reject this story
            raise NoVideoAvailable(
                f"No video available for story '{story.title[:60]}' section '{section}'. "
                "YouTube and Pixabay both failed. Skipping to next story."
            )

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

        logger.info(f"Trying article URL for video: {url}")
        try:
            with yt_dlp.YoutubeDL(self._ydl_opts()) as ydl:
                info = ydl.extract_info(url, download=True)
                ext = info.get("ext", "mp4")
                video_path = self.output_dir / f"source_video.{ext}"
                subs_path = next(self.output_dir.glob("source_video.*.vtt"), None)
                if video_path.exists():
                    logger.info("Article video downloaded successfully")
                    return str(video_path), str(subs_path) if subs_path else None
        except Exception as e:
            logger.warning(f"Article URL download failed: {e}")

        return self._youtube_search(title)

    def _youtube_api_search(self, title: str) -> Optional[str]:
        """Use YouTube Data API v3 to find best video ID — no bot detection on search."""
        if not self.youtube_api_key:
            return None
        try:
            resp = requests.get(
                YOUTUBE_SEARCH_API,
                params={
                    "key": self.youtube_api_key,
                    "q": f"{title} crypto news",
                    "part": "snippet",
                    "type": "video",
                    "maxResults": 1,
                    "videoDuration": "short",
                    "order": "relevance",
                },
                timeout=15,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            if items:
                video_id = items[0]["id"]["videoId"]
                snippet_title = items[0]["snippet"]["title"]
                logger.info(f"YouTube API found: [{video_id}] {snippet_title}")
                return video_id
        except Exception as e:
            logger.warning(f"YouTube API search failed: {e}")
        return None

    def _youtube_search(self, title: str) -> tuple[Optional[str], Optional[str]]:
        # Try API search first to get exact video ID, then download that ID
        video_id = self._youtube_api_search(title)
        if video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
            logger.info(f"Downloading YouTube video by ID: {video_id}")
            try:
                with yt_dlp.YoutubeDL(self._ydl_opts()) as ydl:
                    ydl.download([url])
                video_path = next(self.output_dir.glob("source_video.*"), None)
                subs_path = next(self.output_dir.glob("source_video.*.vtt"), None)
                if video_path and video_path.stat().st_size > 10_000:
                    logger.info("YouTube video downloaded successfully")
                    return str(video_path), str(subs_path) if subs_path else None
            except Exception as e:
                logger.warning(f"YouTube download by ID failed: {e}")
            time.sleep(3)  # back off before fallback

        # Fallback: yt-dlp keyword search
        search_query = f"ytsearch1:{title} crypto news"
        logger.info(f"YouTube keyword search fallback: {search_query}")
        try:
            with yt_dlp.YoutubeDL(self._ydl_opts()) as ydl:
                info = ydl.extract_info(search_query, download=True)
                entries = info.get("entries") or [info]
                ext = entries[0].get("ext", "mp4") if entries else "mp4"
                video_path = self.output_dir / f"source_video.{ext}"
                subs_path = next(self.output_dir.glob("source_video.*.vtt"), None)
                if video_path.exists():
                    logger.info("YouTube keyword search downloaded successfully")
                    return str(video_path), str(subs_path) if subs_path else None
        except Exception as e:
            logger.warning(f"YouTube keyword search failed: {e}")
        return None, None

    # ── Pixabay ───────────────────────────────────────────────────────────────

    def _pixabay_terms(self, story_title: str) -> str:
        title_lower = story_title.lower()
        for keyword, term in CRYPTO_PIXABAY_KEYWORDS.items():
            if keyword in title_lower:
                return term
        return "cryptocurrency blockchain finance"

    def _fetch_pixabay_video(self, story_title: str, section: str, index: int) -> Optional[str]:
        if not self.pixabay_api_key:
            logger.warning("PIXABAY_API_KEY not set")
            return None

        search_term = self._pixabay_terms(story_title)
        logger.info(f"Pixabay fallback for '{section}': '{search_term}'")

        try:
            resp = requests.get(
                PIXABAY_API_URL,
                params={"key": self.pixabay_api_key, "q": search_term, "video_type": "film", "per_page": 10, "safesearch": "true"},
                timeout=15,
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
            if not hits:
                logger.warning(f"Pixabay no results for '{search_term}'")
                return None

            hit = hits[index % len(hits)]
            videos = hit.get("videos", {})
            video_info = videos.get("medium") or videos.get("small") or videos.get("large") or videos.get("tiny")
            if not video_info:
                return None

            out_path = self.output_dir / f"{section}_pixabay.mp4"
            dl = requests.get(video_info["url"], timeout=60, stream=True)
            dl.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in dl.iter_content(chunk_size=1 << 16):
                    f.write(chunk)

            if out_path.exists() and out_path.stat().st_size > 10_000:
                logger.info(f"Pixabay video saved: {out_path}")
                return str(out_path)

        except Exception as e:
            logger.warning(f"Pixabay fetch failed: {e}")
        return None

    # ── Utilities ──────────────────────────────────────────────────────────────

    def _parse_subtitles(self, subs_path: str) -> list[dict]:
        try:
            subs = webvtt.read(subs_path)
            return [{"start": c.start_in_seconds, "end": c.end_in_seconds, "text": c.text.replace("\n", " ")} for c in subs]
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
                        f"Transcript:\n" + "\n".join(lines) +
                        f"\n\nFind a ~{target_duration}s segment. Respond ONLY with JSON: {{\"start_time\": float, \"end_time\": float}}"
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
