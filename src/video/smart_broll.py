import logging
import os
import random
import subprocess
import time
from pathlib import Path
from typing import Optional

import requests
import webvtt
from pydantic import BaseModel, Field

from src.models.schemas import GeneratedScript, RawStory, VisualCue
from src.video.channel_roster import weighted_sample
from src.video.engagement_crop import engagement_window_start

logger = logging.getLogger(__name__)

PEXELS_API_URL = "https://api.pexels.com/videos/search"
YOUTUBE_SEARCH_API = "https://www.googleapis.com/youtube/v3/search"
# Standard yt-dlp cookie location written by the workflow
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
    # Script section names
    "hook":               ["city night lights", "technology futuristic", "trading floor"],
    "main_explanation":   ["blockchain network", "computer data", "finance analytics"],
    "why_it_matters":     ["business strategy", "investment growth", "stock market"],
    "student_dev_angle":  ["coding computer", "developer laptop", "technology startup"],
    "closing_line":       ["success achievement", "digital world", "cryptocurrency future"],
    # Generic fallbacks
    "context":            ["stock market data", "digital money", "cryptocurrency chart"],
    "breakdown":          ["blockchain network", "computer data", "finance analytics"],
    "implication":        ["business strategy", "investment growth", "digital finance"],
    "cta":                ["success achievement", "technology innovation", "cryptocurrency future"],
    "intro":              ["technology futuristic", "city lights", "finance"],
    "outro":              ["success growth", "digital world", "future technology"],
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
        self.pixabay_api_key = os.getenv("PIXABAY_API_KEY", "")
        # Round-robin across Coverr keys
        self._coverr_keys = [k for k in [
            os.getenv("COVERR_API_KEY_1", ""),
            os.getenv("COVERR_API_KEY_2", ""),
            os.getenv("COVERR_API_KEY_3", ""),
        ] if k]
        self._coverr_idx = 0
        self.youtube_api_key = os.getenv("YOUTUBE_API_KEY", "")
        self._pixabay_timeout_count = 0  # circuit breaker: give up after 2 consecutive timeouts
        self._yt_cookie_path = self._write_cookie_file()

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

    def _proxy_list(self) -> list[str]:
        """Parse WEBSHARE_PROXIES (ip:port:user:pass,...) into yt-dlp proxy URLs."""
        raw = os.getenv("WEBSHARE_PROXIES", "").strip()
        if not raw:
            return []
        proxies = []
        for entry in raw.split(","):
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split(":")
            if len(parts) == 4:
                ip, port, user, password = parts
                proxies.append(f"http://{user}:{password}@{ip}:{port}")
            elif len(parts) == 2:
                # ip:port only — use shared creds from env
                user = os.getenv("WEBSHARE_USER", "")
                password = os.getenv("WEBSHARE_PASS", "")
                if user and password:
                    proxies.append(f"http://{user}:{password}@{entry}")
        return proxies

    def _write_cookie_file(self) -> Optional[str]:
        """Decode YOUTUBE_COOKIES_B64 once at init and write to a temp file."""
        import base64, tempfile
        raw = os.getenv("YOUTUBE_COOKIES_B64", "").strip()
        if not raw:
            logger.warning("YOUTUBE_COOKIES_B64 not set — yt-dlp may hit bot detection")
            return None
        try:
            decoded = base64.b64decode(raw).decode("utf-8")
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
            tmp.write(decoded)
            tmp.flush()
            tmp.close()
            logger.info(f"YouTube cookies loaded: {tmp.name} ({len(decoded)} bytes)")
            return tmp.name
        except Exception as e:
            logger.warning(f"Failed to decode YOUTUBE_COOKIES_B64: {e}")
            return None

    def _ydl_bin_download(self, url: str, outtmpl: str, write_subs: bool = False,
                           proxy_url: str | None = None) -> bool:
        """Download via yt-dlp, routing through a residential proxy when available.

        Proxy routes around GitHub Actions' Azure IP block on YouTube.
        ios,android,web_creator client order still helps with JS challenge bypass.
        """
        sub_flags = ["--write-subs", "--write-auto-subs", "--sub-langs", "en", "--sub-format", "vtt"] if write_subs else []
        proxy_flags = ["--proxy", proxy_url] if proxy_url else []
        cookie_flags = ["--cookies", self._yt_cookie_path] if self._yt_cookie_path else []
        cmd = [
            "yt-dlp",
            "-f", "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]/best[height<=720]/best",
            "-o", outtmpl,
            "--no-playlist",
            "--extractor-args", "youtube:player_client=ios,android,web_creator",
            "--socket-timeout", "30",
        ] + proxy_flags + cookie_flags + sub_flags + [url]
        logger.info(f"yt-dlp cmd: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning(f"yt-dlp failed: {result.stderr[-400:] if result.stderr else 'no stderr'}")
        return result.returncode == 0

    def _ydl_with_proxy_rotation(self, url: str, outtmpl: str, write_subs: bool = False) -> bool:
        """Try download with each proxy in random order, fall back to direct."""
        proxies = self._proxy_list()
        random.shuffle(proxies)
        # Try proxies first
        for proxy_url in proxies:
            ip = proxy_url.split("@")[-1]
            logger.info(f"Trying proxy {ip}...")
            if self._ydl_bin_download(url, outtmpl, write_subs=write_subs, proxy_url=proxy_url):
                logger.info(f"Proxy succeeded: {ip}")
                return True
            logger.warning(f"Proxy failed: {ip}")
        # Fall back to direct (works locally, fails on GH Actions without proxy)
        if proxies:
            logger.info("All proxies failed — trying direct connection")
        return self._ydl_bin_download(url, outtmpl, write_subs=write_subs)

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
        youtube_succeeded = False
        yt_audio_path = None

        # ── Step 1: Try YouTube first (real news footage) ────────────────────
        logger.info("Trying YouTube for b-roll...")
        yt_video_path, yt_subs_path = self._download_youtube(story.url, story.title)
        if yt_video_path and Path(yt_video_path).exists() and Path(yt_video_path).stat().st_size > 50_000:
            logger.info(f"YouTube b-roll acquired: {yt_video_path}")
            youtube_succeeded = True
            # Extract original audio so pipeline can use it instead of TTS
            yt_audio_path = self._extract_audio(yt_video_path)
            if yt_audio_path:
                logger.info(f"YouTube audio extracted for non-TTS mode: {yt_audio_path}")
            # Use the YouTube clip for every section (compositor trims to section duration)
            for cue in script.visual_plan:
                media_paths[cue.section] = yt_video_path
        else:
            logger.info("YouTube failed or unavailable — falling back to Pexels")

        # ── Step 2: All sources in parallel per section — pick best result ──────
        if not youtube_succeeded:
            logger.info(f"Fetching b-roll for {len(script.visual_plan)} sections (all sources parallel)...")
            from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed

            def _fetch_section(args):
                i, cue = args
                section = cue.section
                safe = self._safe_section_name(section)
                desc = cue.description or ""

                if (self.output_dir / f"{safe}_broll.mp4").exists() and \
                   (self.output_dir / f"{safe}_broll.mp4").stat().st_size > 10_000:
                    logger.info(f"B-roll cache hit for '{section}'")
                    return section, str(self.output_dir / f"{safe}_broll.mp4")

                # Fetch from ALL sources simultaneously
                candidates: list[tuple[str, str, int]] = []  # (source, path, score)

                with ThreadPoolExecutor(max_workers=3) as inner:
                    f_pexels = inner.submit(
                        self._fetch_pexels_video_for_section,
                        story.title, section, i, desc,
                        self.output_dir / f"{safe}_pexels.mp4"
                    )
                    f_pixabay = inner.submit(
                        self._fetch_pixabay_video,
                        story.title, section, i, desc,
                        self.output_dir / f"{safe}_pixabay.mp4"
                    ) if self.pixabay_api_key else None
                    f_coverr = inner.submit(
                        self._fetch_coverr_video,
                        story.title, section, i, desc,
                        self.output_dir / f"{safe}_coverr.mp4"
                    ) if self._coverr_keys else None

                    for label, fut in [("pexels", f_pexels), ("pixabay", f_pixabay), ("coverr", f_coverr)]:
                        if fut is None:
                            continue
                        try:
                            path = fut.result()
                            if path and Path(path).exists():
                                size = Path(path).stat().st_size
                                candidates.append((label, path, size))
                                logger.info(f"  [{label}] {section}: {size//1024}KB")
                        except Exception as e:
                            logger.warning(f"  [{label}] {section} failed: {e}")

                if not candidates:
                    logger.warning(f"All sources failed for '{section}'")
                    return section, None

                # Pick the largest file as proxy for best quality/resolution
                best_label, best_path, best_size = max(candidates, key=lambda x: x[2])
                logger.info(f"  ✓ Best for '{section}': {best_label} ({best_size//1024}KB)")
                return section, best_path

            with ThreadPoolExecutor(max_workers=len(script.visual_plan)) as pool:
                futures = {pool.submit(_fetch_section, (i, cue)): cue
                           for i, cue in enumerate(script.visual_plan)}
                for fut in _as_completed(futures):
                    section, ppath = fut.result()
                    if ppath:
                        media_paths[section] = ppath
                    else:
                        logger.warning(f"No b-roll found for section '{section}'")

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

        if youtube_succeeded:
            broll_source = "youtube"
        elif any("pexels" in p for p in media_paths.values()):
            broll_source = "pexels"
        else:
            broll_source = "motion_graphics"
        logger.info(f"B-roll source: {broll_source} | sections covered: {list(media_paths.keys())}")
        return media_paths, broll_source, yt_audio_path

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
        if self._ydl_with_proxy_rotation(url, outtmpl, write_subs=True):
            video_path = next(self.output_dir.glob("source_video.mp4"), None) or next(self.output_dir.glob("source_video.*"), None)
            subs_path = next(self.output_dir.glob("source_video.*.vtt"), None)
            if video_path and video_path.exists():
                logger.info("Article video downloaded successfully")
                return str(video_path), str(subs_path) if subs_path else None

        return self._youtube_search(title)

    @staticmethod
    def _trim_title_for_search(title: str) -> str:
        """Reduce a long article title to 4-5 key terms for YouTube search."""
        import re as _re
        # Strip numbers (prices, percentages) and very common filler words
        stop = {"the", "a", "an", "in", "on", "at", "to", "of", "for", "and", "or",
                "is", "are", "was", "were", "has", "have", "with", "from", "by",
                "after", "amid", "amid", "above", "below", "over", "under",
                "remains", "remain", "following", "continues", "continue",
                "report", "reports", "says", "amid", "despite", "per", "via"}
        words = _re.sub(r'[^a-zA-Z\s]', ' ', title).split()
        key_words = [w for w in words if w.lower() not in stop and len(w) > 2]
        return " ".join(key_words[:5])

    def _youtube_api_search(self, title: str) -> list[tuple[str, str]]:
        """Search YouTube Data API within weighted crypto channels — 3 channels × 2 results = 6 candidates."""
        if not self.youtube_api_key:
            return []
        search_title = self._trim_title_for_search(title)
        candidates: list[tuple[str, str]] = []
        for channel_alias in weighted_sample(3):
            query = f"{search_title} {channel_alias}"
            try:
                resp = requests.get(
                    YOUTUBE_SEARCH_API,
                    params={
                        "key": self.youtube_api_key,
                        "q": query,
                        "part": "snippet",
                        "type": "video",
                        "maxResults": 3,
                        "videoDuration": "medium",  # 4-20 min — skips Shorts
                        "order": "relevance",
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                items = resp.json().get("items", [])
                for item in items:
                    vid = item["id"]["videoId"]
                    snippet_title = item["snippet"]["title"]
                    # skip Shorts by title heuristic
                    if "#shorts" not in snippet_title.lower() and "short" not in snippet_title.lower():
                        candidates.append((vid, snippet_title))
            except Exception as e:
                logger.warning(f"YouTube channel search failed for '{channel_alias}': {e}")
        logger.info(f"YouTube channel search found {len(candidates)} candidates")
        return candidates

    def _youtube_search(self, title: str) -> tuple[Optional[str], Optional[str]]:
        # Try each API result in sequence until one downloads successfully
        candidates = self._youtube_api_search(title)
        outtmpl = str(self.output_dir / "source_video.%(ext)s")
        for video_id, snippet_title in candidates:
            url = f"https://www.youtube.com/watch?v={video_id}"
            logger.info(f"Trying YouTube [{video_id}] {snippet_title}")
            # Try with subs first; fall back to no-subs if subs trigger 429
            success = self._ydl_with_proxy_rotation(url, outtmpl, write_subs=True)
            if not success:
                logger.info(f"Retrying [{video_id}] without subtitles")
                success = self._ydl_with_proxy_rotation(url, outtmpl, write_subs=False)
            if success:
                video_path = next(self.output_dir.glob("source_video.mp4"), None) or next(self.output_dir.glob("source_video.*"), None)
                subs_path = next(self.output_dir.glob("source_video.*.vtt"), None)
                if video_path and video_path.stat().st_size > 10_000:
                    logger.info(f"YouTube downloaded: {video_id}")
                    return str(video_path), str(subs_path) if subs_path else None
            time.sleep(2)

        return None, None

    # ── Pixabay ───────────────────────────────────────────────────────────────

    @staticmethod
    def _safe_section_name(section: str) -> str:
        """Normalize section name to a safe filename slug."""
        import re
        return re.sub(r'[^a-z0-9_]', '_', section.lower().strip()).strip('_') or "section"

    def _fetch_pexels_video_for_section(self, story_title: str, section: str, index: int,
                                         cue_description: str = "", out_path=None) -> Optional[str]:
        """Fetch a unique Pexels video using cue description + section themes for visual variety."""
        if not self.pexels_api_key:
            logger.warning("PEXELS_API_KEY not set")
            return None

        safe = self._safe_section_name(section)
        if out_path is None:
            out_path = self.output_dir / f"{safe}_broll.mp4"

        section_themes = SECTION_PIXABAY_THEMES.get(safe) or SECTION_PIXABAY_THEMES.get(section, [])
        story_term = self._pixabay_terms(story_title)
        # Use cue description as first search term for maximum relevance/variety
        cue_term = " ".join(cue_description.split()[:4]) if cue_description else ""
        search_terms = (
            ([cue_term] if cue_term else []) +
            section_themes + [story_term] +
            [t for t in self.FALLBACK_PIXABAY_TERMS if t not in section_themes and t != story_term]
        )

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

    def _fetch_pixabay_video(self, story_title: str, section: str, index: int,
                              cue_description: str = "", out_path=None) -> Optional[str]:
        """Fetch from Pixabay using cue description → section theme → story keyword → fallbacks."""
        if not self.pixabay_api_key:
            return None
        if self._pixabay_timeout_count >= 2:
            logger.warning(f"Pixabay circuit breaker open — skipping section '{section}'")
            return None

        safe = self._safe_section_name(section)
        if out_path is None:
            out_path = self.output_dir / f"{safe}_broll.mp4"

        section_themes = SECTION_PIXABAY_THEMES.get(safe) or SECTION_PIXABAY_THEMES.get(section, [])
        story_term = self._pixabay_terms(story_title)
        cue_term = " ".join(cue_description.split()[:4]) if cue_description else ""
        search_terms = (
            ([cue_term] if cue_term else []) +
            section_themes + [story_term] +
            [t for t in self.FALLBACK_PIXABAY_TERMS if t != story_term]
        )

        for term in search_terms:
            logger.info(f"Pixabay [{section}] searching: '{term}'")
            try:
                resp = requests.get(
                    "https://pixabay.com/api/videos/",
                    params={"key": self.pixabay_api_key, "q": term, "video_type": "film",
                            "per_page": 20, "safesearch": "true"},
                    timeout=15,
                )
                resp.raise_for_status()
                hits = resp.json().get("hits", [])
                if not hits:
                    continue
                offset = (index * 3) % len(hits)
                for hit in (hits[offset:offset+3] or hits[:3]):
                    videos = hit.get("videos", {})
                    video_info = (videos.get("medium") or videos.get("large")
                                  or videos.get("small") or videos.get("tiny"))
                    if not video_info:
                        continue
                    try:
                        dl = requests.get(video_info["url"], timeout=60, stream=True)
                        dl.raise_for_status()
                        with open(out_path, "wb") as f:
                            for chunk in dl.iter_content(chunk_size=1 << 16):
                                f.write(chunk)
                        if Path(out_path).stat().st_size > 10_000:
                            logger.info(f"Pixabay [{section}] saved ({term}): {out_path}")
                            return str(out_path)
                    except Exception as e:
                        logger.warning(f"Pixabay download failed: {e}")
            except Exception as e:
                logger.warning(f"Pixabay search failed for '{term}': {e}")
                if "timed out" in str(e).lower() or "Read timed out" in str(e):
                    self._pixabay_timeout_count += 1
                    if self._pixabay_timeout_count >= 2:
                        logger.warning("Pixabay circuit breaker tripped — aborting Pixabay for this run")
                        return None

        logger.error(f"Pixabay exhausted all terms for section '{section}'")
        return None

    def _next_coverr_key(self) -> str:
        if not self._coverr_keys:
            return ""
        key = self._coverr_keys[self._coverr_idx % len(self._coverr_keys)]
        self._coverr_idx += 1
        return key

    def _fetch_coverr_video(self, story_title: str, section: str, index: int,
                             cue_description: str = "", out_path=None) -> Optional[str]:
        """Fetch from Coverr.co using API key."""
        if not self._coverr_keys:
            return None
        safe = self._safe_section_name(section)
        if out_path is None:
            out_path = self.output_dir / f"{safe}_broll.mp4"

        section_themes = SECTION_PIXABAY_THEMES.get(safe) or SECTION_PIXABAY_THEMES.get(section, [])
        story_term = self._pixabay_terms(story_title)
        cue_term = " ".join(cue_description.split()[:3]) if cue_description else ""
        search_terms = ([cue_term] if cue_term else []) + section_themes + [story_term] + self.FALLBACK_PIXABAY_TERMS

        api_key = self._next_coverr_key()
        for term in search_terms:
            try:
                resp = requests.get(
                    "https://coverr.co/api/videos",
                    params={"page": 1, "q": term},
                    headers={"User-Agent": "Mozilla/5.0", "Authorization": f"Bearer {api_key}"},
                    timeout=15,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                hits = data.get("hits", data.get("data", data.get("videos", [])))
                if not hits:
                    continue
                hit = hits[index % len(hits)]
                sources = hit.get("sources") or []
                url = (sources[0].get("src") if sources else None) or hit.get("url") or hit.get("mp4")
                if not url:
                    continue
                logger.info(f"Coverr [{section}] downloading ({term}): {url[:80]}")
                dl = requests.get(url, timeout=60, stream=True, headers={"User-Agent": "Mozilla/5.0"})
                dl.raise_for_status()
                with open(out_path, "wb") as f:
                    for chunk in dl.iter_content(chunk_size=1 << 16):
                        f.write(chunk)
                if Path(out_path).stat().st_size > 10_000:
                    logger.info(f"Coverr [{section}] saved: {out_path}")
                    return str(out_path)
            except Exception as e:
                logger.warning(f"Coverr failed for '{term}': {e}")
        return None

    def _fetch_archive_video(self, story_title: str, section: str, index: int,
                              cue_description: str = "", out_path=None) -> Optional[str]:
        """Fetch public domain video from Internet Archive."""
        safe = self._safe_section_name(section)
        if out_path is None:
            out_path = self.output_dir / f"{safe}_broll.mp4"

        story_term = self._pixabay_terms(story_title)
        cue_term = " ".join(cue_description.split()[:3]) if cue_description else ""
        search_terms = ([cue_term] if cue_term else []) + [story_term, "finance technology", "cryptocurrency", "digital economy"]

        for term in search_terms:
            try:
                resp = requests.get(
                    "https://archive.org/advancedsearch.php",
                    params={
                        "q": f"{term} AND mediatype:movies",
                        "fl[]": ["identifier", "title"],
                        "rows": 10,
                        "output": "json",
                        "page": 1,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                docs = resp.json().get("response", {}).get("docs", [])
                if not docs:
                    continue
                doc = docs[index % len(docs)]
                identifier = doc.get("identifier")
                if not identifier:
                    continue
                # Get the actual file listing
                meta = requests.get(f"https://archive.org/metadata/{identifier}", timeout=15)
                meta.raise_for_status()
                files = meta.json().get("files", [])
                mp4s = [f for f in files if f.get("name", "").endswith(".mp4")]
                if not mp4s:
                    continue
                mp4 = mp4s[0]
                url = f"https://archive.org/download/{identifier}/{mp4['name']}"
                logger.info(f"Archive [{section}] downloading: {identifier}/{mp4['name']}")
                dl = requests.get(url, timeout=120, stream=True)
                dl.raise_for_status()
                with open(out_path, "wb") as f:
                    for chunk in dl.iter_content(chunk_size=1 << 16):
                        f.write(chunk)
                if Path(out_path).stat().st_size > 10_000:
                    logger.info(f"Archive [{section}] saved: {out_path}")
                    return str(out_path)
            except Exception as e:
                logger.warning(f"Archive failed for '{term}': {e}")
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
