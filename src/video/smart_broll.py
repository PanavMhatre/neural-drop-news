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
from src.video.channel_roster import weighted_sample
from src.video.engagement_crop import engagement_window_start

logger = logging.getLogger(__name__)

YOUTUBE_SEARCH_API = "https://www.googleapis.com/youtube/v3/search"
# Prefer up to 4K, falling back progressively — shared by both the direct
# yt-dlp download and the Oracle WARP proxy request below so a source-quality
# fix made once in this string applies to whichever path actually succeeds.
YT_DLP_FORMAT_SELECTOR = (
    "bv*[ext=mp4][height<=2160]+ba[ext=m4a]/bv*[ext=mp4][height<=1080]+ba[ext=m4a]/"
    "b[ext=mp4][height<=2160]/best"
)


class NoVideoAvailable(Exception):
    """Raised when no video source could be acquired for a story — pipeline should skip it."""


class TimestampMatch(BaseModel):
    start_time: float = Field(description="Start time in seconds")
    end_time: float = Field(description="End time in seconds")


class SmartBRollAgent:
    """
    Video acquisition: YouTube only — real footage from real creators/edited
    videos, never generic stock B-roll (Pexels/Pixabay/Coverr/Archive.org were
    removed on request; they produced generic, disconnected-from-the-story
    footage). If no suitable YouTube source can be found or downloaded, raises
    NoVideoAvailable so the pipeline skips the story rather than rendering
    with stock filler.
    """

    def __init__(self, output_dir: str, openai_client):
        self.output_dir = Path(output_dir) / "media"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.client = openai_client
        self.youtube_api_key = os.getenv("YOUTUBE_API_KEY", "")
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

    def _ydl_via_oracle_proxy(self, url: str, outtmpl: str, write_subs: bool = False) -> bool:
        """Download YouTube video via Oracle VM WARP proxy.

        The Oracle VM runs yt-dlp with --source-address 172.16.0.2 (Cloudflare WARP),
        routing traffic through Cloudflare IPs that YouTube trusts.
        """
        proxy_base = os.getenv("ORACLE_PROXY_URL", "").rstrip("/")
        if not proxy_base:
            return False
        try:
            import tempfile, shutil
            secret = os.getenv("ORACLE_PROXY_SECRET", "")
            headers = {"Authorization": f"Bearer {secret}"} if secret else {}
            # WARP is the primary/preferred download path in production
            # (ORACLE_PROXY_URL is set in CI), so it must carry the same
            # resolution hint as the direct yt-dlp fallback below — otherwise
            # the remote service picks its own default format and the "download
            # up to 4K" fix only ever applies on the rarer fallback path.
            # If the remote service doesn't read this field, it's ignored.
            payload = {"url": url, "write_subs": write_subs, "format": YT_DLP_FORMAT_SELECTOR}
            logger.info(f"Oracle WARP download: {proxy_base}/download <- {url}")
            resp = requests.post(
                f"{proxy_base}/download",
                json=payload,
                headers=headers,
                timeout=120,
                stream=True,
            )
            if resp.status_code != 200:
                body = resp.text[:300]
                logger.warning(f"Oracle proxy error {resp.status_code}: {body}")
                return False
            # Determine extension from Content-Disposition or default to mp4
            cd = resp.headers.get("Content-Disposition", "")
            ext = "mp4"
            if "filename=" in cd:
                fname = cd.split("filename=")[-1].strip().strip('"')
                ext = fname.rsplit(".", 1)[-1] if "." in fname else "mp4"
            # outtmpl may contain %(ext)s — resolve it
            out_path = outtmpl.replace("%(ext)s", ext)
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "wb") as f:
                shutil.copyfileobj(resp.raw, f)
            size = Path(out_path).stat().st_size
            logger.info(f"Oracle proxy saved: {out_path} ({size // 1024}KB)")
            return size > 50_000
        except Exception as e:
            logger.warning(f"Oracle proxy failed: {e}")
            return False

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
            "-f", YT_DLP_FORMAT_SELECTOR,
            "-o", outtmpl,
            "--no-playlist",
            "--extractor-args", "youtube:player_client=tv_embedded,ios,android",
            "--socket-timeout", "30",
        ] + proxy_flags + cookie_flags + sub_flags + [url]
        logger.info(f"yt-dlp cmd: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning(f"yt-dlp failed: {result.stderr[-400:] if result.stderr else 'no stderr'}")
        return result.returncode == 0

    def _ydl_with_proxy_rotation(self, url: str, outtmpl: str, write_subs: bool = False) -> bool:
        """Download via Oracle VM WARP proxy (primary) then fall back to direct yt-dlp.

        Webshare residential proxies have been removed — Oracle WARP exits via
        Cloudflare IPs (104.28.x.x) which YouTube does not block.
        """
        if os.getenv("ORACLE_PROXY_URL"):
            if self._ydl_via_oracle_proxy(url, outtmpl, write_subs=write_subs):
                return True
            logger.warning("Oracle WARP proxy failed — falling back to direct yt-dlp")
        return self._ydl_bin_download(url, outtmpl, write_subs=write_subs)

    def acquire_media(
        self, script: GeneratedScript, story: RawStory
    ) -> tuple[dict[str, str], str, Optional[str]]:
        """
        Returns (media_paths, broll_source, youtube_audio_path).

        broll_source: always "youtube" on success.
        youtube_audio_path: path to the original YouTube audio track (mux back in
            instead of TTS), or None if audio extraction failed.

        Raises NoVideoAvailable if YouTube footage can't be found/downloaded —
        there is no stock-footage or motion-graphics fallback. Real edited
        video only; the pipeline skips the story rather than using filler.
        """
        media_paths: dict[str, str] = {}

        logger.info("Fetching YouTube b-roll...")
        yt_video_path, yt_subs_path = self._download_youtube(story.url, story.title)
        if not (yt_video_path and Path(yt_video_path).exists() and Path(yt_video_path).stat().st_size > 50_000):
            raise NoVideoAvailable(
                f"YouTube B-roll unavailable for '{story.title[:60]}' — story skipped"
            )

        logger.info(f"YouTube b-roll acquired: {yt_video_path}")
        # Extract original audio so the pipeline can use it instead of TTS
        yt_audio_path = self._extract_audio(yt_video_path)
        if yt_audio_path:
            logger.info(f"YouTube audio extracted for non-TTS mode: {yt_audio_path}")

        # Match each section to the part of the SOURCE video that's actually
        # talking about the same thing, instead of playing the download
        # straight through from frame 0. A single downloaded video routinely
        # contains an intro bumper, a sponsor segment (e.g. an exchange app
        # download ad), and the actual news coverage all in one file — linear
        # playback puts whatever's chronologically next on screen regardless
        # of what the narration says at that moment, which is exactly what
        # "the background doesn't match what's being said" looks like.
        transcript = self._parse_subtitles(yt_subs_path) if yt_subs_path else []
        if not transcript:
            logger.warning("No transcript available — per-section matching skipped, using engagement-window trim only")

        def _match_and_trim(cue: VisualCue) -> tuple[str, Optional[str]]:
            safe = "".join(c if c.isalnum() else "_" for c in cue.section).strip("_") or "section"
            start_t, end_t = self._find_best_segment(cue, transcript, default_start=0.0)
            trimmed_path = str(self.output_dir / f"{safe}_matched.mp4")
            if self._trim_video(yt_video_path, trimmed_path, start_t, end_t):
                return cue.section, trimmed_path
            return cue.section, None

        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=min(5, max(1, len(script.visual_plan)))) as pool:
            futures = {pool.submit(_match_and_trim, cue): cue for cue in script.visual_plan}
            for fut in as_completed(futures):
                cue = futures[fut]
                try:
                    section, matched_path = fut.result()
                except Exception as e:
                    logger.warning(f"Segment match/trim failed for '{cue.section}': {e}")
                    section, matched_path = cue.section, None
                # Fall back to the full source video for this section if
                # matching or trimming failed — still real footage, just
                # without the content-relevance match.
                media_paths[section] = matched_path or yt_video_path

        logger.info(f"B-roll source: youtube | sections covered: {list(media_paths.keys())}")
        return media_paths, "youtube", yt_audio_path

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
            # Re-encode (not stream copy): -c:v copy can only cut on a source
            # keyframe, so the ML-matched start time gets silently rounded to
            # the nearest keyframe — often several seconds off for a clip this
            # short, showing the wrong footage before the intended segment.
            # CRF 16 (near-lossless) + veryslow preset: this clip gets read
            # frame-by-frame and re-encoded again in the final render, so any
            # softness introduced here compounds into the final output. Clips
            # are short (a few seconds each), so the extra time is negligible
            # against the full pipeline's time budget.
            "-c:v", "libx264", "-preset", "veryslow", "-crf", "16", "-an",
            output_path,
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return Path(output_path).exists()
        except subprocess.CalledProcessError:
            return False
