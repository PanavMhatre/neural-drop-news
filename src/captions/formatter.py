"""
Caption formatter — generates SRT and ASS caption files.

Groups words into readable caption lines optimized for mobile
viewing on 9:16 vertical video.
"""

import logging
import re
from pathlib import Path
from typing import Optional

from src.models.schemas import CaptionLine, WordTimestamp

logger = logging.getLogger(__name__)

# Company/asset/protocol names to highlight
HIGHLIGHT_TERMS = {
    # Core crypto assets
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol",
    "xrp", "ripple", "cardano", "ada", "dogecoin", "doge",
    "polygon", "matic", "avalanche", "avax", "chainlink", "link",
    "litecoin", "ltc", "bnb",
    # Stablecoins & DeFi
    "usdt", "usdc", "tether", "stablecoin", "defi",
    "uniswap", "aave", "lido", "maker", "compound", "curve",
    # Exchanges & major companies
    "coinbase", "binance", "kraken", "gemini", "bitfinex", "okx", "bybit",
    "microstrategy", "circle", "grayscale", "blackrock", "fidelity",
    "galaxy digital",
    # Regulation & market structure
    "sec", "etf", "cftc", "fed",
    # Legacy AI/tech terms (still appear occasionally in crossover stories)
    "openai", "gpt", "chatgpt", "anthropic", "claude",
    "google", "nvidia", "microsoft", "amazon", "tesla", "meta",
    "ai", "ml", "api",
    "billion", "million", "trillion",
}


class CaptionFormatter:
    """Formats word timestamps into caption files."""

    def __init__(self, config: dict):
        self.config = config
        self.words_per_line = config.get("words_per_line", 2)
        self.highlight_companies = config.get("highlight_companies", True)
        self.highlight_numbers = config.get("highlight_numbers", True)

    def create_caption_lines(
        self, word_timestamps: list[WordTimestamp]
    ) -> list[CaptionLine]:
        """
        Group word timestamps into readable caption lines.

        Args:
            word_timestamps: Word-level timing data.

        Returns:
            List of CaptionLine objects.
        """
        if not word_timestamps:
            return []

        lines: list[CaptionLine] = []
        current_words: list[WordTimestamp] = []

        for word_ts in word_timestamps:
            current_words.append(word_ts)

            # Break line at word limit or sentence boundary
            should_break = (
                len(current_words) >= self.words_per_line
                or word_ts.word.rstrip().endswith((".", "!", "?", ",", ";", ":"))
            )

            if should_break and current_words:
                line = self._create_line(current_words)
                lines.append(line)
                current_words = []

        # Remaining words
        if current_words:
            line = self._create_line(current_words)
            lines.append(line)

        return lines

    def _create_line(self, words: list[WordTimestamp]) -> CaptionLine:
        """Create a CaptionLine from a group of words."""
        text = " ".join(w.word for w in words)

        # Find words to highlight
        highlighted = []
        if self.highlight_companies or self.highlight_numbers:
            for w in words:
                clean_word = re.sub(r"[^\w-]", "", w.word.lower())
                if self.highlight_companies and clean_word in HIGHLIGHT_TERMS:
                    highlighted.append(w.word)
                elif self.highlight_numbers and re.match(r"\d", clean_word):
                    highlighted.append(w.word)

        # Remove commas and dashes as requested by user
        text = text.replace(",", "").replace("-", " ").replace("—", " ")
        text = re.sub(r"\s+", " ", text).strip()
        
        highlighted = [
            re.sub(r"\s+", " ", h.replace(",", "").replace("-", " ").replace("—", " ")).strip()
            for h in highlighted
        ]

        return CaptionLine(
            text=text,
            start_time=words[0].start,
            end_time=words[-1].end,
            words=words,
            highlighted_words=highlighted,
        )

    def export_srt(
        self, caption_lines: list[CaptionLine], output_path: str
    ) -> str:
        """
        Export captions as an SRT file.

        Returns:
            Path to the generated SRT file.
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        srt_content = []
        for i, line in enumerate(caption_lines, 1):
            start = self._format_srt_time(line.start_time)
            end = self._format_srt_time(line.end_time)
            srt_content.append(f"{i}")
            srt_content.append(f"{start} --> {end}")
            srt_content.append(line.text)
            srt_content.append("")  # Blank line separator

        output_file.write_text("\n".join(srt_content), encoding="utf-8")
        logger.info(f"SRT exported: {output_path} ({len(caption_lines)} lines)")
        return str(output_file)

    def export_ass(
        self,
        caption_lines: list[CaptionLine],
        output_path: str,
        video_width: int = 1080,
        video_height: int = 1920,
        font_size: int = 56,
        accent_color: tuple[int, int, int] = (0, 200, 255),
    ) -> str:
        """
        Export captions as an ASS (Advanced SubStation Alpha) file with styling.

        The ASS format supports styled text, positioning, and animations,
        making it suitable for burn-in rendering.

        Returns:
            Path to the generated ASS file.
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Convert accent color to ASS format (BGR in hex)
        r, g, b = accent_color
        ass_color = f"&H00{b:02X}{g:02X}{r:02X}"  # ASS uses &HBBGGRR format
        ass_highlight = f"&H00{b:02X}{g:02X}{r:02X}"

        # ASS header
        ass_content = f"""[Script Info]
Title: TechPulse Shorts Captions
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Inter,{font_size},&H00FFFFFF,{ass_highlight},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,2,40,40,200,1
Style: Highlight,Inter,{font_size},{ass_color},{ass_highlight},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,2,40,40,200,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        for line in caption_lines:
            start = self._format_ass_time(line.start_time)
            end = self._format_ass_time(line.end_time)

            # Build text with highlighted words
            if line.highlighted_words:
                text = line.text
                for hw in line.highlighted_words:
                    # Wrap highlighted words in style override
                    text = text.replace(
                        hw,
                        f"{{\\c{ass_highlight}\\b1}}{hw}{{\\c&H00FFFFFF\\b0}}"
                    )
            else:
                text = line.text

            ass_content += f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n"

        output_file.write_text(ass_content, encoding="utf-8")
        logger.info(f"ASS exported: {output_path} ({len(caption_lines)} lines)")
        return str(output_file)

    @staticmethod
    def _format_srt_time(seconds: float) -> str:
        """Format seconds as SRT timestamp: HH:MM:SS,mmm"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    @staticmethod
    def _format_ass_time(seconds: float) -> str:
        """Format seconds as ASS timestamp: H:MM:SS.cc"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centisecs = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"
