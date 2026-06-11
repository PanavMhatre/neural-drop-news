"""
Whisper-based audio alignment for word-level caption timestamps.

Takes generated voiceover audio and produces precise word-level
timing data for caption synchronization.
"""

import logging
from pathlib import Path
from typing import Optional

from src.models.schemas import WordTimestamp

logger = logging.getLogger(__name__)


class WhisperAligner:
    """Aligns audio to text using local Whisper model for word-level timestamps."""

    def __init__(self, config: dict):
        self.config = config
        self.model_name = config.get("whisper_model", "base")
        self._model = None
        self._whisper = None

    def _load_model(self):
        """Lazy-load the Whisper model."""
        if self._model is None:
            try:
                import whisper_timestamped as whisper
                self._whisper = whisper
                logger.info(f"Loading Whisper model: {self.model_name}")
                self._model = whisper.load_model(self.model_name)
                logger.info("Whisper model loaded")
            except ImportError:
                logger.warning(
                    "whisper-timestamped not installed. "
                    "Falling back to estimated timestamps. "
                    "Install with: pip install whisper-timestamped"
                )
                self._model = None
                self._whisper = None

    def align_audio(
        self,
        audio_path: str,
        script_text: Optional[str] = None,
    ) -> list[WordTimestamp]:
        """
        Get word-level timestamps from audio file.

        Args:
            audio_path: Path to the voiceover MP3/WAV file.
            script_text: Original script text (for validation).

        Returns:
            List of WordTimestamp with precise timing for each word.
        """
        self._load_model()

        if self._model is None or self._whisper is None:
            # Fallback: estimate timestamps from script text
            logger.warning("Using estimated timestamps (Whisper not available)")
            return self._estimate_timestamps(script_text or "", audio_path)

        try:
            audio = self._whisper.load_audio(audio_path)
            result = self._whisper.transcribe(
                self._model,
                audio,
                language="en",
                vad=True,  # Voice Activity Detection to avoid hallucinations
            )

            words = []
            for segment in result.get("segments", []):
                for word_data in segment.get("words", []):
                    words.append(WordTimestamp(
                        word=word_data["text"].strip(),
                        start=round(word_data["start"], 3),
                        end=round(word_data["end"], 3),
                    ))

            logger.info(f"Aligned {len(words)} words from audio")
            return words

        except Exception as e:
            logger.error(f"Whisper alignment failed: {e}")
            logger.warning("Falling back to estimated timestamps")
            return self._estimate_timestamps(script_text or "", audio_path)

    def _estimate_timestamps(
        self, script_text: str, audio_path: str
    ) -> list[WordTimestamp]:
        """
        Estimate word timestamps based on text length and audio duration.

        This is a rough fallback when Whisper is not available.
        """
        # Try to get audio duration
        duration = self._get_audio_duration(audio_path)
        if duration is None:
            # Estimate from word count (avg ~3 words per second)
            words = script_text.split()
            duration = len(words) / 3.0

        words = script_text.split()
        if not words:
            return []

        # Distribute time evenly across words
        time_per_word = duration / len(words)

        timestamps = []
        current_time = 0.0

        for word in words:
            # Longer words get slightly more time
            word_factor = max(0.7, min(1.5, len(word) / 5.0))
            word_duration = time_per_word * word_factor

            timestamps.append(WordTimestamp(
                word=word,
                start=round(current_time, 3),
                end=round(current_time + word_duration, 3),
            ))
            current_time += word_duration

        # Normalize to fit actual duration
        if timestamps and duration > 0:
            scale = duration / timestamps[-1].end
            for ts in timestamps:
                ts.start = round(ts.start * scale, 3)
                ts.end = round(ts.end * scale, 3)

        return timestamps

    def _get_audio_duration(self, audio_path: str) -> Optional[float]:
        """Try to get audio duration using ffprobe."""
        try:
            import subprocess
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    audio_path,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
        except (subprocess.SubprocessError, ValueError, FileNotFoundError):
            pass
        return None
