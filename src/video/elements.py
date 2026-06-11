"""
Visual elements — reusable drawing functions for video frames.

Provides functions to draw progress bars, source footers, watermarks,
accent lines, cards, and text with effects.
"""

import logging
import textwrap
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

# Font cache
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def get_font(font_path: str, size: int) -> ImageFont.FreeTypeFont:
    """Get or create a cached font object."""
    key = (font_path, size)
    if key not in _font_cache:
        try:
            _font_cache[key] = ImageFont.truetype(font_path, size)
        except (OSError, IOError):
            logger.warning(f"Font not found: {font_path}, using default")
            _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


def draw_gradient_background(
    img: Image.Image,
    color_top: tuple[int, int, int],
    color_bottom: tuple[int, int, int],
) -> None:
    """Draw a vertical gradient background on the image."""
    width, height = img.size
    draw = ImageDraw.Draw(img)

    for y in range(height):
        ratio = y / height
        r = int(color_top[0] + (color_bottom[0] - color_top[0]) * ratio)
        g = int(color_top[1] + (color_bottom[1] - color_top[1]) * ratio)
        b = int(color_top[2] + (color_bottom[2] - color_top[2]) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))


def draw_solid_background(
    img: Image.Image,
    color: tuple[int, int, int],
) -> None:
    """Fill with a solid color."""
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), img.size], fill=color)


def draw_progress_bar(
    img: Image.Image,
    progress: float,
    accent_color: tuple[int, int, int],
    bar_height: int = 4,
    y_position: Optional[int] = None,
) -> None:
    """Draw a thin progress bar at the top or bottom of the frame."""
    draw = ImageDraw.Draw(img)
    width, height = img.size

    if y_position is None:
        y_position = height - bar_height

    # Background bar (subtle)
    draw.rectangle(
        [(0, y_position), (width, y_position + bar_height)],
        fill=(40, 40, 60),
    )

    # Progress fill
    fill_width = int(width * max(0.0, min(1.0, progress)))
    if fill_width > 0:
        draw.rectangle(
            [(0, y_position), (fill_width, y_position + bar_height)],
            fill=accent_color,
        )


def draw_source_footer(
    img: Image.Image,
    source_text: str,
    font: ImageFont.FreeTypeFont,
    y_position: int,
    text_color: tuple[int, int, int] = (120, 120, 150),
    bg_opacity: int = 128,
) -> None:
    """No-op: source attribution belongs in metadata, not burned into videos."""
    return None


def draw_watermark(
    img: Image.Image,
    text: str,
    font: ImageFont.FreeTypeFont,
    position: str = "top_right",
    color: tuple[int, int, int] = (80, 80, 100),
    margin: int = 30,
) -> None:
    """Draw a small channel watermark."""
    draw = ImageDraw.Draw(img)
    width, height = img.size

    bbox = font.getbbox(text)
    text_width = bbox[2] - bbox[0]

    if position == "top_right":
        x = width - text_width - margin
        y = margin
    elif position == "top_left":
        x = margin
        y = margin
    elif position == "bottom_right":
        x = width - text_width - margin
        y = height - margin - 30
    else:
        x = margin
        y = height - margin - 30

    draw.text((x, y), text, fill=color, font=font)


def draw_accent_line(
    img: Image.Image,
    accent_color: tuple[int, int, int],
    y_position: int,
    line_width: int = 4,
    margin: int = 60,
    length_ratio: float = 0.3,
) -> None:
    """Draw a decorative accent line."""
    draw = ImageDraw.Draw(img)
    width, _ = img.size

    line_length = int(width * length_ratio)
    x_start = (width - line_length) // 2
    x_end = x_start + line_length

    draw.rectangle(
        [(x_start, y_position), (x_end, y_position + line_width)],
        fill=accent_color,
    )


def draw_card(
    img: Image.Image,
    y_start: int,
    y_end: int,
    accent_color: tuple[int, int, int],
    opacity: float = 0.12,
    margin: int = 40,
    corner_radius: int = 20,
) -> None:
    """Draw a semi-transparent card background."""
    width, _ = img.size

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    alpha = int(255 * opacity)
    card_color = (*accent_color, alpha)

    overlay_draw.rounded_rectangle(
        [(margin, y_start), (width - margin, y_end)],
        radius=corner_radius,
        fill=card_color,
    )

    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))


def draw_glow(
    img: Image.Image,
    center_x: int,
    center_y: int,
    accent_color: tuple[int, int, int],
    radius: int = 100,
    opacity: float = 0.15,
) -> None:
    """Draw a soft glow effect around a point."""
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)

    alpha = int(255 * opacity)
    glow_draw.ellipse(
        [
            (center_x - radius, center_y - radius),
            (center_x + radius, center_y + radius),
        ],
        fill=(*accent_color, alpha),
    )

    # Blur for soft glow
    glow = glow.filter(ImageFilter.GaussianBlur(radius=radius // 2))

    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"))


def draw_text_centered(
    img: Image.Image,
    text: str,
    font: ImageFont.FreeTypeFont,
    y: int,
    color: tuple[int, int, int] = (255, 255, 255),
    max_width: Optional[int] = None,
    opacity: float = 1.0,
    shadow: bool = True,
    shadow_offset: int = 3,
    line_spacing: int = 12,
) -> int:
    """
    Draw centered text with optional wrapping, shadow, and opacity.

    Returns the Y position after the last line of text.
    """
    draw = ImageDraw.Draw(img)
    width, _ = img.size

    if max_width is None:
        max_width = width - 100  # Default margins

    # Wrap text
    lines = _wrap_text(text, font, max_width)

    # Apply opacity to color
    if opacity < 1.0:
        color = tuple(int(c * opacity) for c in color)

    current_y = y
    for line in lines:
        bbox = font.getbbox(line)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (width - text_width) // 2

        # Shadow
        if shadow and opacity > 0.5:
            shadow_color = (0, 0, 0)
            draw.text((x + shadow_offset, current_y + shadow_offset), line, fill=shadow_color, font=font)

        # Main text
        draw.text((x, current_y), line, fill=color, font=font)
        current_y += text_height + line_spacing

    return current_y


def draw_caption_text(
    img: Image.Image,
    text: str,
    font: ImageFont.FreeTypeFont,
    y: int,
    color: tuple[int, int, int] = (255, 255, 255),
    highlight_words: list[str] = None,
    accent_color: tuple[int, int, int] = (0, 200, 255),
    opacity: float = 1.0,
) -> None:
    """Draw caption text with highlighted words."""
    draw = ImageDraw.Draw(img)
    width, _ = img.size

    if highlight_words is None:
        highlight_words = []

    # Apply opacity
    if opacity < 1.0:
        color = tuple(int(c * opacity) for c in color)
        accent_color = tuple(int(c * opacity) for c in accent_color)

    # Measure full text width
    bbox = font.getbbox(text)
    total_width = bbox[2] - bbox[0]
    start_x = (width - total_width) // 2

    # Draw shadow
    draw.text((start_x + 3, y + 3), text, fill=(0, 0, 0), font=font)

    # Draw word by word for highlighting
    words = text.split()
    highlight_lower = {w.lower().strip(".,!?;:") for w in highlight_words}
    current_x = start_x

    for i, word in enumerate(words):
        word_display = word + (" " if i < len(words) - 1 else "")
        clean_word = word.lower().strip(".,!?;:")

        word_color = accent_color if clean_word in highlight_lower else color
        draw.text((current_x, y), word_display, fill=word_color, font=font)

        word_bbox = font.getbbox(word_display)
        current_x += word_bbox[2] - word_bbox[0]


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = font.getbbox(test_line)
        if bbox[2] - bbox[0] <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]

    if current_line:
        lines.append(" ".join(current_line))

    return lines if lines else [text]


def draw_cta_banner(
    img: Image.Image,
    cta_text: str,
    link_text: str,
    font: ImageFont.FreeTypeFont,
    accent_color: tuple[int, int, int] = (0, 200, 255),
    opacity: float = 1.0,
    banner_height_ratio: float = 0.12,
    brand_font: Optional[ImageFont.FreeTypeFont] = None,
    tagline_font: Optional[ImageFont.FreeTypeFont] = None,
    brand_name: str = "NEURAL DROP",
    tagline: str = "The 3-minute AI briefing for students, builders, and creators.",
) -> None:
    """
    Draw a professional Neural Drop CTA end card overlay.

    Renders a full-frame dark gradient overlay with:
    - Large brand name centered
    - Tagline underneath
    - Accent line separator
    - Link highlighted in accent color
    - Smooth opacity support for fade-in

    Args:
        img: The frame image to draw on.
        cta_text: The CTA prompt (e.g. "Get the daily AI briefing →").
        link_text: The link to highlight (e.g. "bit.ly/neural-drop").
        font: Font for the CTA text line.
        accent_color: Color for accents and the link.
        opacity: Overall opacity (0.0-1.0) for animated fade-in.
        banner_height_ratio: Unused (kept for API compat).
        brand_font: Large font for the brand name. Falls back to font if None.
        tagline_font: Smaller font for the tagline. Falls back to font if None.
        brand_name: The brand name to display (default "NEURAL DROP").
        tagline: Tagline text below the brand.
    """
    width, height = img.size

    if opacity < 0.02:
        return

    # --- 1. Full-frame dark gradient overlay ---
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    # Gradient from semi-transparent at top to nearly opaque at bottom
    top_alpha = int(160 * opacity)
    bottom_alpha = int(230 * opacity)
    for y in range(height):
        ratio = y / height
        alpha = int(top_alpha + (bottom_alpha - top_alpha) * ratio)
        overlay_draw.line([(0, y), (width, y)], fill=(5, 5, 15, alpha))

    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))

    draw = ImageDraw.Draw(img)

    # --- 2. Calculate vertical center layout ---
    center_y = int(height * 0.42)

    # Use provided fonts or fall back
    b_font = brand_font or font
    t_font = tagline_font or font

    # --- 3. Brand name "NEURAL DROP" ---
    brand_bbox = b_font.getbbox(brand_name)
    brand_w = brand_bbox[2] - brand_bbox[0]
    brand_h = brand_bbox[3] - brand_bbox[1]
    brand_x = (width - brand_w) // 2
    brand_y = center_y

    brand_color = tuple(int(c * opacity) for c in (255, 255, 255))

    # Shadow
    draw.text((brand_x + 3, brand_y + 3), brand_name, fill=(0, 0, 0), font=b_font)
    # Main text
    draw.text((brand_x, brand_y), brand_name, fill=brand_color, font=b_font)

    # --- 4. Accent line separator ---
    line_y = brand_y + brand_h + int(height * 0.025)
    line_length = int(width * 0.25)
    line_x_start = (width - line_length) // 2
    line_alpha = int(255 * opacity)
    accent_with_opacity = tuple(int(c * opacity) for c in accent_color)

    # Draw accent line using overlay for clean alpha
    line_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    line_draw = ImageDraw.Draw(line_overlay)
    line_draw.rectangle(
        [(line_x_start, line_y), (line_x_start + line_length, line_y + 3)],
        fill=(*accent_color, line_alpha),
    )
    img.paste(Image.alpha_composite(img.convert("RGBA"), line_overlay).convert("RGB"))

    # Re-acquire draw after paste
    draw = ImageDraw.Draw(img)

    # --- 5. Tagline ---
    tagline_y = line_y + int(height * 0.03)
    # Wrap tagline if needed
    tagline_lines = _wrap_text(tagline, t_font, int(width * 0.75))
    tagline_color = tuple(int(c * opacity) for c in (180, 180, 200))

    current_y = tagline_y
    for tl in tagline_lines:
        tl_bbox = t_font.getbbox(tl)
        tl_w = tl_bbox[2] - tl_bbox[0]
        tl_h = tl_bbox[3] - tl_bbox[1]
        tl_x = (width - tl_w) // 2
        draw.text((tl_x, current_y), tl, fill=tagline_color, font=t_font)
        current_y += tl_h + 6

    # --- 6. CTA + Link ---
    cta_y = current_y + int(height * 0.04)

    # CTA text in white, link in accent
    full_cta = f"{cta_text}  {link_text}"
    cta_bbox = font.getbbox(full_cta)
    cta_total_w = cta_bbox[2] - cta_bbox[0]
    cta_h = cta_bbox[3] - cta_bbox[1]
    cta_x = (width - cta_total_w) // 2

    cta_color = tuple(int(c * opacity) for c in (220, 220, 230))
    link_color = tuple(int(c * opacity) for c in accent_color)

    # Shadow
    draw.text((cta_x + 2, cta_y + 2), full_cta, fill=(0, 0, 0), font=font)

    # CTA text
    draw.text((cta_x, cta_y), cta_text + "  ", fill=cta_color, font=font)

    # Link text highlighted
    cta_part_bbox = font.getbbox(cta_text + "  ")
    link_x = cta_x + (cta_part_bbox[2] - cta_part_bbox[0])
    draw.text((link_x, cta_y), link_text, fill=link_color, font=font)

    # --- 7. Bottom pill/badge ---
    badge_y = cta_y + cta_h + int(height * 0.04)
    badge_text = "LINK IN BIO"
    badge_bbox = font.getbbox(badge_text)
    badge_w = badge_bbox[2] - badge_bbox[0]
    badge_h = badge_bbox[3] - badge_bbox[1]
    badge_x = (width - badge_w) // 2

    # Draw rounded pill background
    pill_pad_x = 30
    pill_pad_y = 12
    pill_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pill_draw = ImageDraw.Draw(pill_overlay)
    pill_alpha = int(200 * opacity)
    pill_draw.rounded_rectangle(
        [
            (badge_x - pill_pad_x, badge_y - pill_pad_y),
            (badge_x + badge_w + pill_pad_x, badge_y + badge_h + pill_pad_y),
        ],
        radius=badge_h,
        fill=(*accent_color, pill_alpha),
    )
    img.paste(Image.alpha_composite(img.convert("RGBA"), pill_overlay).convert("RGB"))

    draw = ImageDraw.Draw(img)
    badge_text_color = tuple(int(c * opacity) for c in (255, 255, 255))
    draw.text((badge_x, badge_y), badge_text, fill=badge_text_color, font=font)


def draw_persistent_pill(
    img: Image.Image,
    cta_text: str,
    link_text: str,
    font: ImageFont.FreeTypeFont,
    accent_color: tuple[int, int, int],
    y_position: int,
    opacity: float = 1.0,
):
    """
    Draw a persistent pill-shaped CTA that stays on screen for the full video.
    """
    if opacity < 0.02:
        return

    width, height = img.size
    
    full_text = f"{cta_text} {link_text}"
    text_bbox = font.getbbox(full_text)
    text_w = text_bbox[2] - text_bbox[0]
    text_h = text_bbox[3] - text_bbox[1]
    
    pad_x = 24
    pad_y = 12
    
    pill_w = text_w + (pad_x * 2)
    pill_h = text_h + (pad_y * 2)
    pill_x = (width - pill_w) // 2
    
    # Draw pill background
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    
    # Dark semi-transparent pill base
    base_alpha = int(220 * opacity)
    draw_overlay.rounded_rectangle(
        [(pill_x, y_position), (pill_x + pill_w, y_position + pill_h)],
        radius=pill_h // 2,
        fill=(15, 20, 25, base_alpha),
        outline=(*accent_color, int(150 * opacity)),
        width=2
    )
    
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))
    
    draw = ImageDraw.Draw(img)
    
    # Text drawing
    text_x = pill_x + pad_x
    text_y = y_position + pad_y
    
    # Split CTA and link to color link with accent color
    cta_color = tuple(int(c * opacity) for c in (255, 255, 255))
    link_color = tuple(int(c * opacity) for c in accent_color)
    
    draw.text((text_x, text_y), cta_text + " ", fill=cta_color, font=font)
    
    cta_part_bbox = font.getbbox(cta_text + " ")
    link_x = text_x + (cta_part_bbox[2] - cta_part_bbox[0])
    
    draw.text((link_x, text_y), link_text, fill=link_color, font=font)
