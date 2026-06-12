from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
FONT_BOLD = ROOT / "assets" / "fonts" / "Montserrat" / "Montserrat-ExtraBold.ttf"
FONT_SEMI = ROOT / "assets" / "fonts" / "Montserrat" / "Montserrat-SemiBold.ttf"

CTA_TEXT = "Get the 3-minute AI briefing"
CTA_LINK = "bit.ly/neural-drop"
CTA_BADGE = "LINK IN BIO"
BRAND = "NEURAL DROP"
SAFE_CTA_PILL_Y = 1650


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    fallback = Path("/System/Library/Fonts/Helvetica.ttc")
    return ImageFont.truetype(str(path if path.exists() else fallback), size)


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        probe = f"{current} {word}".strip()
        if draw.textbbox((0, 0), probe, font=fnt)[2] <= max_width:
            current = probe
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    fnt: ImageFont.FreeTypeFont,
    y: int,
    fill: tuple[int, int, int, int],
    width: int = 1080,
) -> int:
    bbox = draw.textbbox((0, 0), text, font=fnt)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    draw.text(((width - text_w) // 2, y), text, font=fnt, fill=fill)
    return y + text_h


def draw_cta_pill(
    img: Image.Image,
    y: int = 1470,
    cta_text: str = CTA_TEXT,
    cta_link: str = CTA_LINK,
) -> None:
    draw = ImageDraw.Draw(img, "RGBA")
    text_font = font(FONT_SEMI, 34)
    link_font = font(FONT_BOLD, 34)
    full = f"{cta_text}  {cta_link}"
    bbox = draw.textbbox((0, 0), full, font=text_font)
    pill_w = min(980, bbox[2] - bbox[0] + 72)
    pill_h = 78
    x = (1080 - pill_w) // 2

    draw.rounded_rectangle(
        (x, y, x + pill_w, y + pill_h),
        radius=pill_h // 2,
        fill=(5, 8, 12, 235),
        outline=(54, 211, 153, 230),
        width=3,
    )

    text_x = x + 36
    text_y = y + 20
    draw.text((text_x, text_y), f"{cta_text}  ", font=text_font, fill=(255, 255, 255, 255))
    cta_w = draw.textbbox((0, 0), f"{cta_text}  ", font=text_font)[2]
    draw.text((text_x + cta_w, text_y - 1), cta_link, font=link_font, fill=(54, 211, 153, 255))


def make_cta_overlay(path: Path, pill_y: int = SAFE_CTA_PILL_Y) -> None:
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw_cta_pill(img, y=pill_y)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def make_cta_endcard(path: Path) -> None:
    img = Image.new("RGB", (1080, 1920), (4, 7, 12))
    draw = ImageDraw.Draw(img, "RGBA")
    brand_font = font(FONT_BOLD, 88)
    title_font = font(FONT_BOLD, 70)
    body_font = font(FONT_SEMI, 38)
    badge_font = font(FONT_BOLD, 34)

    for y in range(1920):
        alpha = int(30 + 110 * (y / 1920))
        draw.line((0, y, 1080, y), fill=(10, 20, 28, alpha))

    y = 430
    y = draw_centered_text(draw, BRAND, brand_font, y, (255, 255, 255, 255)) + 42
    draw.rounded_rectangle((380, y, 700, y + 8), radius=4, fill=(54, 211, 153, 255))
    y += 82

    for line in wrap(draw, CTA_TEXT, title_font, 880)[:2]:
        y = draw_centered_text(draw, line, title_font, y, (255, 255, 255, 255)) + 18

    y += 28
    body = "Top AI moves, source links, and the stories worth watching."
    for line in wrap(draw, body, body_font, 830)[:3]:
        y = draw_centered_text(draw, line, body_font, y, (203, 213, 225, 255)) + 14

    y += 56
    link_w = draw.textbbox((0, 0), CTA_LINK, font=title_font)[2]
    draw.text(((1080 - link_w) // 2, y), CTA_LINK, font=title_font, fill=(54, 211, 153, 255))
    y += 122

    badge_bbox = draw.textbbox((0, 0), CTA_BADGE, font=badge_font)
    badge_w = badge_bbox[2] - badge_bbox[0]
    badge_x = (1080 - badge_w) // 2
    draw.rounded_rectangle((badge_x - 36, y - 18, badge_x + badge_w + 36, y + 52), radius=35, fill=(54, 211, 153, 255))
    draw.text((badge_x, y - 4), CTA_BADGE, font=badge_font, fill=(4, 7, 12, 255))

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG", quality=95)
