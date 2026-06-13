import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

import requests
import webvtt
from pydantic import BaseModel, Field

from src.models.schemas import GeneratedScript, RawStory, VisualCue
from src.video.engagement_crop import engagement_window_start

logger = logging.getLogger(__name__)

PEXELS_API_URL = "https://api.pexels.com/videos/search"
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
    "cme": "stock market trading",
    "futures": "finance trading",
    "xrp": "cryptocurrency market",
    "ripple": "digital currency",
}

# Per-section visual variety — each script section gets a different visual theme
SECTION_PIXABAY_THEMES = {
    "hook":        ["city night lights", "technology futuristic", "finance trading floor"],
    "context":     ["stock market data", "digital money", "cryptocurrency chart"],
    "breakdown":   ["blockchain network", "computer data", "finance analytics"],
    "implication": ["business strategy", "investment growth", "digital finance"],
    "cta":         ["success achievement", "technology innovation", "cryptocurrency future"],
    "intro":       ["technology futuristic", "city lights", "finance"],
    "outro":       ["success growth", "digital world", "future technology"],
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
        self.pexels_api_key = os.getenv("PEXELS_API_KEY", "RnbckPtXv2kk3u4CaTIA0jv1T0IxZRT0MTxbd4LDUAw4qUid3KxOtwOY")
        self.youtube_api_key = os.getenv("YOUTUBE_API_KEY", "")

        # Cookie file: env override or standard yt-dlp location written by workflow
        cookie_env = os.getenv("YOUTUBE_COOKIES_FILE", "")
        self.cookies_file = cookie_env if cookie_env else YTDLP_COOKIE_PATH

        self.model = "openai/gpt-oss-20b"
        # Use NVIDIA OSS pool if available, otherwise fall back to passed client
        oss_keys = [os.getenv(f"NVIDIA_OSS_KEY_{i}", "") for i in range(1, 11)]
        oss_keys = [k for k in oss_keys if k]
        if not oss_keys:
            oss_keys = [os.getenv(f"NVIDIA_API_KEY_{i}", "") for i in range(1, 6)]
            oss_keys = [k for k in oss_keys if k]
        if oss_keys:
            from openai import OpenAI as _OAI
            self.client = _OAI(api_key=oss_keys[0], base_url="https://integrate.api.nvidia.com/v1")

    def _ydl_bin_download(self, url: str, outtmpl: str, write_subs: bool = False) -> bool:
        """Run yt-dlp via python -m so bgutil PO token plugin (site-packages) is loaded."""
        cookie_path = Path.home() / ".config/yt-dlp/cookies.txt"
        if cookie_path.exists():
            logger.info(f"yt-dlp cookies present: {cookie_path} ({cookie_path.stat().st_size} bytes)")
        else:
            logger.warning(f"No yt-dlp cookie file at {cookie_path}")
        cmd = [
            "python", "-m", "yt_dlp",
            "-f", "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]/best[height<=720]/best",
            "-o", outtmpl,
            "--no-playlist",
        ]
        if write_subs:
            cmd += ["--write-subs", "--write-auto-subs", "--sub-langs", "en", "--sub-format", "vtt"]
        cmd.append(url)
        logger.info(f"yt-dlp cmd: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=False)
        return result.returncode == 0

    def acquire_media(
        self, script: GeneratedScript, story: RawStory, accent_color: tuple
    ) -> tuple[dict[str, str], str, Optional[str]]:
        """
        Returns (media_paths, broll_source, youtube_audio_path).

        broll_source: "youtube" | "pixabay" | "motion_graphics"
        youtube_audio_path: path to the original YouTube audio track (mux back in
            instead of TTS) when broll_source == "youtube", else None.
        """
        from src.video import motion_graphics as mg

        media_paths: dict[str, str] = {}

        # Fetch a UNIQUE Pexels video for EVERY section.
        # Each section gets its own search term for visual variety.
        logger.info(f"Fetching unique Pexels video for each of {len(script.visual_plan)} sections (parallel)...")
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _fetch_section(args):
            i, cue = args
            section = cue.section
            out_path = self.output_dir / f"{section}_pexels.mp4"
            if out_path.exists() and out_path.stat().st_size > 10_000:
                logger.info(f"Pexels cache hit for '{section}'")
                return section, str(out_path)
            ppath = self._fetch_pexels_video_for_section(story.title, section, i)
            return section, ppath

        with ThreadPoolExecutor(max_workers=len(script.visual_plan)) as pool:
            futures = {pool.submit(_fetch_section, (i, cue)): cue
                       for i, cue in enumerate(script.visual_plan)}
            for fut in as_completed(futures):
                section, ppath = fut.result()
                if ppath:
                    media_paths[section] = ppath
                else:
                    logger.warning(f"Pexels failed for section '{section}', using motion graphic")

        youtube_succeeded = False

        # Any section still missing: motion graphics last resort
        for i, cue in enumerate(script.visual_plan):
            section = cue.section
            if section not in media_paths:
                logger.warning(f"No video for '{section}', generating motion graphic")
                mg_path = str(self.output_dir / f"{section}_motion.mp4")
                duration = cue.duration_hint or 8.0
                if mg.generate_for_section(mg_path, story.title, section, accent_color, duration):
                    media_paths[section] = mg_path
                else:
                    raise NoVideoAvailable(
                        f"All video sources failed for story '{story.title[:60]}' section '{section}'."
                    )

        # Fill-forward: any section missing a video gets the nearest available clip
        all_sections = [cue.section for cue in script.visual_plan]
        last_good: Optional[str] = None
        forward_fill: dict[str, str] = {}
        for sec in all_sections:
            if sec in media_paths:
                last_good = media_paths[sec]
            elif last_good:
                forward_fill[sec] = last_good
                logger.info(f"Fill-forward: section '{sec}' uses video from previous section")

        first_good: Optional[str] = None
        for sec in all_sections:
            if sec in media_paths:
                first_good = media_paths[sec]
                break
        for sec in all_sections:
            if sec not in media_paths and sec not in forward_fill and first_good:
                forward_fill[sec] = first_good
                logger.info(f"Fill-back: section '{sec}' uses video from first available section")

        media_paths.update(forward_fill)

        broll_source = "pexels" if any("pexels" in p for p in media_paths.values()) else "motion_graphics"
        logger.info(f"B-roll source: {broll_source} | sections covered: {list(media_paths.keys())}")
        return media_paths, broll_source, None

    def _extract_audio(self, video_path: str) -> Optional[str]:
        """Extract audio track from a video file to mp3."""
        out = str(self.output_dir / "yt_audio.mp3")
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vn", "-acodec", "libmp3lame", "-q:a", "3",
            "-t", "120",  # cap at 2 min
            out,
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            if Path(out).exists() and Path(out).stat().st_size > 5000:
                logger.info(f"YouTube audio extracted: {out}")
                return out
        except Exception as e:
            logger.warning(f"Audio extraction failed: {e}")
        return None

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
        outtmpl = str(self.output_dir / "source_video.%(ext)s")
        if self._ydl_bin_download(url, outtmpl, write_subs=True):
            video_path = next(self.output_dir.glob("source_video.mp4"), None) or next(self.output_dir.glob("source_video.*"), None)
            subs_path = next(self.output_dir.glob("source_video.*.vtt"), None)
            if video_path and video_path.exists():
                logger.info("Article video downloaded successfully")
                return str(video_path), str(subs_path) if subs_path else None

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
        # Try API search first to get exact video ID, then download by ID via binary
        video_id = self._youtube_api_search(title)
        if video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
            logger.info(f"Downloading YouTube video by ID: {video_id}")
            outtmpl = str(self.output_dir / "source_video.%(ext)s")
            if self._ydl_bin_download(url, outtmpl, write_subs=True):
                video_path = next(self.output_dir.glob("source_video.mp4"), None) or next(self.output_dir.glob("source_video.*"), None)
                subs_path = next(self.output_dir.glob("source_video.*.vtt"), None)
                if video_path and video_path.stat().st_size > 10_000:
                    logger.info("YouTube video downloaded successfully")
                    return str(video_path), str(subs_path) if subs_path else None
            time.sleep(3)

        # Fallback: yt-dlp binary keyword search
        search_query = f"ytsearch1:{title} crypto news"
        logger.info(f"YouTube keyword search fallback: {search_query}")
        outtmpl = str(self.output_dir / "source_video.%(ext)s")
        if self._ydl_bin_download(search_query, outtmpl, write_subs=True):
            video_path = next(self.output_dir.glob("source_video.mp4"), None) or next(self.output_dir.glob("source_video.*"), None)
            subs_path = next(self.output_dir.glob("source_video.*.vtt"), None)
            if video_path and video_path.exists():
                logger.info("YouTube keyword search downloaded successfully")
                return str(video_path), str(subs_path) if subs_path else None
        return None, None

    # ── Pixabay ───────────────────────────────────────────────────────────────

    def _fetch_pexels_video_for_section(self, story_title: str, section: str, index: int) -> Optional[str]:
        """Fetch a unique Pexels video using section-specific search terms for visual variety."""
        if not self.pexels_api_key:
            logger.warning("PEXELS_API_KEY not set")
            return None

        section_themes = SECTION_PIXABAY_THEMES.get(section, [])
        story_term = self._pixabay_terms(story_title)
        search_terms = section_themes + [story_term] + [
            t for t in self.FALLBACK_PIXABAY_TERMS if t not in section_themes and t != story_term
        ]

        out_path = self.output_dir / f"{section}_pexels.mp4"
        headers = {"Authorization": self.pexels_api_key}

        for term in search_terms:
            logger.info(f"Pexels [{section}] searching: '{term}'")
            try:
                resp = requests.get(
                    PEXELS_API_URL,
                    headers=headers,
                    params={"query": term, "per_page": 15, "orientation": "portrait"},
                    timeout=20,
                )
                resp.raise_for_status()
                videos = resp.json().get("videos", [])
                if not videos:
                    continue

                # Pick a different video per section using index offset
                offset = (index * 3) % len(videos)
                candidates = videos[offset:offset + 3] or videos[:3]

                for video in candidates:
                    # Pick best quality video file that fits portrait 1080p
                    files = video.get("video_files", [])
                    # Prefer HD portrait files, fall back to any
                    files_sorted = sorted(
                        [f for f in files if f.get("height", 0) >= 720],
                        key=lambda f: f.get("height", 0),
                        reverse=True,
                    ) or files
                    if not files_sorted:
                        continue
                    url = files_sorted[0].get("link")
                    if not url:
                        continue
                    try:
                        dl = requests.get(url, timeout=60, stream=True)
                        dl.raise_for_status()
                        with open(out_path, "wb") as f:
                            for chunk in dl.iter_content(chunk_size=1 << 16):
                                f.write(chunk)
                        if out_path.exists() and out_path.stat().st_size > 10_000:
                            logger.info(f"Pexels [{section}] saved ({term}): {out_path}")
                            return str(out_path)
                    except Exception as e:
                        logger.warning(f"Pexels download failed: {e}")
                        continue
            except Exception as e:
                logger.warning(f"Pexels search failed for '{term}': {e}")
                continue

        logger.error(f"Pexels exhausted all terms for section '{section}'")
        return None

    def _pixabay_terms(self, story_title: str) -> str:
        title_lower = story_title.lower()
        for keyword, term in CRYPTO_PIXABAY_KEYWORDS.items():
            if keyword in title_lower:
                return term
        return "cryptocurrency blockchain finance"

    FALLBACK_PIXABAY_TERMS = [
        "cryptocurrency blockchain",
        "finance technology",
        "digital money",
        "stock market trading",
        "technology futuristic",
        "city lights night",
    ]

    def _fetch_pixabay_video(self, story_title: str, section: str, index: int) -> Optional[str]:
        if not self.pixabay_api_key:
            logger.warning("PIXABAY_API_KEY not set")
            return None

        primary_term = self._pixabay_terms(story_title)
        search_terms = [primary_term] + [t for t in self.FALLBACK_PIXABAY_TERMS if t != primary_term]

        for term in search_terms:
            logger.info(f"Pixabay search for '{section}': '{term}'")
            try:
                resp = requests.get(
                    PIXABAY_API_URL,
                    params={"key": self.pixabay_api_key, "q": term, "video_type": "film", "per_page": 20, "safesearch": "true"},
                    timeout=15,
                )
                resp.raise_for_status()
                hits = resp.json().get("hits", [])
                if not hits:
                    logger.warning(f"Pixabay no results for '{term}', trying next term")
                    continue

                # Try each hit until one downloads successfully
                for attempt, hit in enumerate(hits[index % len(hits):index % len(hits) + 5] or hits[:5]):
                    videos = hit.get("videos", {})
                    video_info = (videos.get("medium") or videos.get("large")
                                  or videos.get("small") or videos.get("tiny"))
                    if not video_info:
                        continue
                    out_path = self.output_dir / f"{section}_pixabay.mp4"
                    try:
                        dl = requests.get(video_info["url"], timeout=60, stream=True)
                        dl.raise_for_status()
                        with open(out_path, "wb") as f:
                            for chunk in dl.iter_content(chunk_size=1 << 16):
                                f.write(chunk)
                        if out_path.exists() and out_path.stat().st_size > 10_000:
                            logger.info(f"Pixabay video saved: {out_path} (term='{term}')")
                            return str(out_path)
                    except Exception as e:
                        logger.warning(f"Pixabay download attempt {attempt} failed: {e}")
                        continue

            except Exception as e:
                logger.warning(f"Pixabay fetch failed for term '{term}': {e}")
                continue

        logger.error(f"All Pixabay search terms exhausted for section '{section}'")
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
            from src.utils.llm import llm_parse
            match = llm_parse(
                self.client,
                self.model,
                [
                    {"role": "system", "content": "You are an AI video editor. Find the best video segment that matches the visual cue."},
                    {"role": "user", "content": (
                        f"Visual Cue: {cue.description}\nText Overlay: {cue.text_overlay}\n\n"
                        f"Transcript:\n" + "\n".join(lines) +
                        f"\n\nFind a ~{target_duration}s segment. Respond ONLY with JSON: {{\"start_time\": float, \"end_time\": float}}"
                    )},
                ],
                TimestampMatch,
                temperature=0.0,
            )
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
