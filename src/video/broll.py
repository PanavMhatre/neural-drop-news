import logging
import os
import random
import requests
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from src.models.schemas import GeneratedScript, RawStory
from src.video import elements as elem

logger = logging.getLogger(__name__)

class BRollAgent:
    """Acquires media assets (b-roll) for video production."""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir) / "media"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.font_dir = Path("./assets/fonts/Inter")

    def acquire_media(self, script: GeneratedScript, story: RawStory, accent_color: tuple[int, int, int]) -> dict[str, str]:
        """
        Acquire 1 image per script section.
        Returns a dict mapping section names to image file paths.
        """
        media_paths = {}
        
        # 1. Try to scrape the main article image for the 'explanation' section
        hero_image_path = self._scrape_hero_image(story.url)
        
        for cue in script.visual_plan:
            section = cue.section
            path = self.output_dir / f"{section}.png"
            
            if section == "explanation" and hero_image_path:
                # Use the scraped article image
                media_paths[section] = hero_image_path
                continue
                
            # Otherwise, generate a dynamic headline/quote graphic
            # Or if it's the hook, maybe just a solid background since the hook text is always on top.
            if section == "hook":
                # For the hook, we might just want a dark, blurred abstract background or a title card
                if hero_image_path:
                    # Reuse the hero image but blurred heavily
                    self._generate_blurred_bg(hero_image_path, str(path), accent_color)
                else:
                    self._generate_abstract_bg(str(path), accent_color)
                media_paths[section] = str(path)
                continue
                
            # Generate a "News Headline" or "Quote" graphic
            text_to_show = cue.text_overlay or cue.description
            self._generate_headline_graphic(str(path), text_to_show, story.source_name, accent_color)
            media_paths[section] = str(path)
            
        return media_paths

    def _scrape_hero_image(self, url: str) -> str | None:
        """Scrape the og:image from the article URL."""
        if not url or url.startswith("mock://"):
            return None
            
        try:
            logger.info(f"Scraping hero image from: {url}")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                return None
                
            soup = BeautifulSoup(resp.text, 'html.parser')
            og_image = soup.find("meta", property="og:image")
            
            if not og_image or not og_image.get("content"):
                return None
                
            image_url = og_image["content"]
            
            # Download the image
            img_resp = requests.get(image_url, headers=headers, stream=True, timeout=10)
            if img_resp.status_code == 200:
                out_path = self.output_dir / "hero.jpg"
                with open(out_path, 'wb') as f:
                    for chunk in img_resp.iter_content(1024):
                        f.write(chunk)
                logger.info(f"Downloaded hero image: {image_url}")
                return str(out_path)
                
        except Exception as e:
            logger.warning(f"Failed to scrape hero image: {e}")
            
        return None

    def _generate_headline_graphic(self, output_path: str, text: str, source_name: str, accent_color: tuple[int, int, int]) -> None:
        """Generate a glossy news popup graphic using Pillow."""
        width, height = 1080, 1920
        img = Image.new("RGB", (width, height), (15, 23, 42))  # Slate 900 background
        
        # Add subtle glow
        elem.draw_glow(img, width//2, height//2, accent_color, radius=600, opacity=0.15)
        
        # Draw the card
        draw = ImageDraw.Draw(img, "RGBA")
        card_w, card_h = 880, 600
        card_x = (width - card_w) // 2
        card_y = (height - card_h) // 2
        
        # Shadow
        draw.rounded_rectangle([card_x-10, card_y-10, card_x+card_w+10, card_y+card_h+10], radius=32, fill=(0,0,0,100))
        # Card Background (glassy)
        draw.rounded_rectangle([card_x, card_y, card_x+card_w, card_y+card_h], radius=24, fill=(30, 41, 59, 230), outline=accent_color, width=2)
        
        # Source badge
        font_path = self._get_font_path("bold")
        source_font = elem.get_font(font_path, 28)
        draw.text((card_x + 40, card_y + 40), str(source_name).upper(), font=source_font, fill=accent_color)
        
        # Headline text
        headline_font = elem.get_font(font_path, 56)
        elem.draw_text_centered(img, text, headline_font, card_y + 250, color=(248, 250, 252), max_width=card_w - 80)
        
        img.save(output_path, "PNG", quality=95)

    def _generate_blurred_bg(self, source_image_path: str, output_path: str, accent_color: tuple[int, int, int]) -> None:
        """Create a heavily blurred version of the hero image for backgrounds."""
        try:
            with Image.open(source_image_path) as img:
                img = img.convert("RGB")
                # Crop to 9:16
                w, h = img.size
                target_ratio = 1080 / 1920
                if w / h > target_ratio:
                    new_w = int(h * target_ratio)
                    offset = (w - new_w) // 2
                    img = img.crop((offset, 0, offset + new_w, h))
                else:
                    new_h = int(w / target_ratio)
                    offset = (h - new_h) // 2
                    img = img.crop((0, offset, w, offset + new_h))
                
                img = img.resize((1080, 1920), Image.Resampling.LANCZOS)
                img = img.filter(ImageFilter.GaussianBlur(radius=40))
                
                # Tint with dark overlay
                overlay = Image.new("RGBA", (1080, 1920), (0, 0, 0, 180))
                img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
                
                img.save(output_path, "PNG", quality=90)
        except Exception as e:
            logger.error(f"Failed to create blurred bg: {e}")
            self._generate_abstract_bg(output_path, accent_color)

    def _generate_abstract_bg(self, output_path: str, accent_color: tuple[int, int, int]) -> None:
        """Create an abstract dark gradient background."""
        img = Image.new("RGB", (1080, 1920))
        elem.draw_gradient_background(img, (9, 9, 11), (15, 23, 42))
        elem.draw_glow(img, 540, 960, accent_color, radius=800, opacity=0.1)
        img.save(output_path, "PNG", quality=90)

    def _get_font_path(self, style: str = "bold") -> str:
        candidates = [
            self.font_dir / f"Inter-{'Bold' if style == 'bold' else 'Regular'}.ttf",
            Path("/System/Library/Fonts/Helvetica.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ]
        for path in candidates:
            if path.exists():
                return str(path)
        return str(candidates[0])
