"""
TTS engine using OpenAI's Text-to-Speech API.

Generates natural AI voiceover with configurable voice, speed,
and tone-based voice selection.
"""

import logging
from pathlib import Path
from typing import Optional

from openai import OpenAI

from src.models.schemas import StoryTone, VoiceConfig

logger = logging.getLogger(__name__)

# Default voice mapping by story tone
DEFAULT_TONE_VOICES = {
    StoryTone.STARTUP_FUNDING: "en-US-GuyNeural",
    StoryTone.DEVELOPER_TOOLS: "en-US-ChristopherNeural",
    StoryTone.AI_SAFETY: "en-US-EricNeural",
    StoryTone.PRODUCT_LAUNCH: "en-US-GuyNeural",
    StoryTone.LAYOFFS_HIRING: "en-US-RogerNeural",
    StoryTone.GENERAL: "en-US-GuyNeural",
}


class TTSEngine:
    """Generates voiceover audio using OpenAI TTS."""

    def __init__(self, client: OpenAI, config: dict):
        self.client = client
        self.config = config
        self.model = config.get("model", "tts-1-hd")
        self.default_voice = config.get("default_voice", "nova")
        self.speed = config.get("speed", 1.05)
        self.tone_voices = {}

        # Build tone → voice mapping
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
        """
        Generate voiceover audio from script text.
        """
        voice = voice_override or self.tone_voices.get(tone, self.default_voice)
        speed = speed_override or self.speed
        provider = provider or self.config.get("provider", "openai")

        voice_config = VoiceConfig(
            voice=voice,
            model=self.model,
            speed=speed,
            tone=tone,
        )

        logger.info(f"Generating voiceover: provider={provider}, voice={voice}, model={self.model}, speed={speed}")

        # Ensure output directory exists
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            if provider == "edge-tts":
                import asyncio
                import edge_tts
                
                # Adjust edge-tts rate parameter based on speed (e.g., 1.05 -> "+5%")
                rate_str = f"+{int((speed - 1.0) * 100)}%" if speed >= 1.0 else f"{int((speed - 1.0) * 100)}%"
                
                async def generate():
                    communicate = edge_tts.Communicate(script_text, voice, rate=rate_str)
                    await communicate.save(output_path)
                    
                asyncio.run(generate())
            else:
                response = self.client.audio.speech.create(
                    model=self.model,
                    voice=voice,
                    input=script_text,
                    speed=speed,
                    response_format="mp3",
                )

                # Stream response to file
                response.stream_to_file(str(output_file))

            file_size = output_file.stat().st_size
            logger.info(f"Voiceover saved: {output_path} ({file_size / 1024:.1f} KB)")

        except Exception as e:
            logger.error(f"TTS generation failed: {e}")
            raise

        return voice_config

    def get_ai_disclosure(self, voice_config: VoiceConfig) -> str:
        """Generate AI narration disclosure text."""
        return (
            f"This video uses AI-generated narration (OpenAI {voice_config.model}, "
            f"voice: {voice_config.voice}) and AI-assisted script writing and editing. "
            f"All facts are sourced from credited publications. "
            f"Content was reviewed by a human before posting."
        )
