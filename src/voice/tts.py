"""
TTS engine: ElevenLabs (primary) → edge-tts (fallback).
"""

import logging
import os
from pathlib import Path
from typing import Optional

import requests
from openai import OpenAI

from src.models.schemas import StoryTone, VoiceConfig

logger = logging.getLogger(__name__)

ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech"
ELEVENLABS_VOICE_ID = "pNInz6obpgDQGcFmaJgB"  # Adam — authoritative news voice

DEFAULT_TONE_VOICES = {
    StoryTone.STARTUP_FUNDING: "en-US-GuyNeural",
    StoryTone.DEVELOPER_TOOLS: "en-US-ChristopherNeural",
    StoryTone.AI_SAFETY: "en-US-EricNeural",
    StoryTone.PRODUCT_LAUNCH: "en-US-GuyNeural",
    StoryTone.LAYOFFS_HIRING: "en-US-RogerNeural",
    StoryTone.GENERAL: "en-US-GuyNeural",
}


class TTSEngine:
    """Generates voiceover audio. ElevenLabs → edge-tts fallback."""

    def __init__(self, client: OpenAI, config: dict):
        self.client = client
        self.config = config
        self.model = config.get("model", "tts-1-hd")
        self.default_voice = config.get("default_voice", "nova")
        self.speed = config.get("speed", 1.05)
        self.tone_voices = {}
        self.elevenlabs_key = os.getenv("ELEVENLABS_API_KEY", "")

        tone_config = config.get("tone_voices", {})
        for tone in StoryTone:
            voice = tone_config.get(tone.value, DEFAULT_TONE_VOICES.get(tone, self.default_voice))
            self.tone_voices[tone] = voice

    def generate_voiceover(
        self,
        script_text: str,
        output_path: str,
        tone: StoryTone = StoryTone.GENERAL,
        voice_override: Optional[str] = None,
        speed_override: Optional[float] = None,
        provider: Optional[str] = None,
    ) -> VoiceConfig:
        voice = voice_override or self.tone_voices.get(tone, self.default_voice)
        speed = speed_override or self.speed
        provider = provider or self.config.get("provider", "elevenlabs")

        voice_config = VoiceConfig(voice=voice, model=self.model, speed=speed, tone=tone)

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Try ElevenLabs first (best quality)
        if self.elevenlabs_key:
            try:
                self._generate_elevenlabs(script_text, output_path)
                logger.info(f"ElevenLabs voiceover saved: {output_path} ({output_file.stat().st_size / 1024:.1f} KB)")
                voice_config.voice = f"elevenlabs:{ELEVENLABS_VOICE_ID}"
                return voice_config
            except Exception as e:
                logger.warning(f"ElevenLabs failed: {e} — falling back to edge-tts")

        # Fallback: edge-tts (free, no key needed)
        try:
            self._generate_edge_tts(script_text, output_path, voice, speed)
            logger.info(f"edge-tts voiceover saved: {output_path} ({output_file.stat().st_size / 1024:.1f} KB)")
            return voice_config
        except Exception as e:
            logger.error(f"All TTS providers failed: {e}")
            raise

    def _generate_elevenlabs(self, text: str, output_path: str) -> None:
        resp = requests.post(
            f"{ELEVENLABS_API_URL}/{ELEVENLABS_VOICE_ID}",
            headers={
                "xi-api-key": self.elevenlabs_key,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": {
                    "stability": 0.55,
                    "similarity_boost": 0.75,
                    "style": 0.3,
                    "use_speaker_boost": True,
                },
            },
            timeout=60,
        )
        resp.raise_for_status()
        Path(output_path).write_bytes(resp.content)
        if Path(output_path).stat().st_size < 1000:
            raise RuntimeError("ElevenLabs returned empty audio")

    def _generate_edge_tts(self, text: str, output_path: str, voice: str, speed: float) -> None:
        import asyncio
        import edge_tts

        rate_str = f"+{int((speed - 1.0) * 100)}%" if speed >= 1.0 else f"{int((speed - 1.0) * 100)}%"

        async def _run():
            communicate = edge_tts.Communicate(text, voice, rate=rate_str)
            await communicate.save(output_path)

        asyncio.run(_run())

    def get_ai_disclosure(self, voice_config: VoiceConfig) -> str:
        return (
            "This video uses AI-generated narration and AI-assisted script writing. "
            "All facts are sourced from credited publications."
        )
