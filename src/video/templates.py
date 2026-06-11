"""
Visual template system with rotation.

Defines different visual styles for videos to ensure variation
across the channel. Each template specifies colors, layouts,
font sizes, and animation styles.
"""

from dataclasses import dataclass, field
from typing import Optional

from src.models.schemas import VisualTemplate


@dataclass
class TemplateConfig:
    """Full visual configuration for a video template."""
    type: VisualTemplate
    name: str

    # Background
    bg_color_top: tuple[int, int, int] = (15, 15, 25)
    bg_color_bottom: tuple[int, int, int] = (25, 25, 45)
    use_gradient: bool = True

    # Text colors
    text_color: tuple[int, int, int] = (255, 255, 255)
    subtitle_color: tuple[int, int, int] = (200, 200, 220)
    muted_color: tuple[int, int, int] = (120, 120, 150)

    # Layout (relative positions, 0.0 = top, 1.0 = bottom)
    hook_y_ratio: float = 0.35          # Hook text Y position
    body_y_ratio: float = 0.45          # Body text Y position
    caption_y_ratio: float = 0.72       # Caption Y position
    source_y_ratio: float = 0.94        # Source footer Y position

    # Font sizes
    hook_font_size: int = 72
    body_font_size: int = 44
    caption_font_size: int = 56
    source_font_size: int = 22
    watermark_font_size: int = 18

    # Accent
    accent_opacity: float = 0.85

    # Animation style
    hook_animation: str = "scale_in"    # scale_in, slide_up, fade_in
    body_animation: str = "slide_up"
    caption_animation: str = "fade_in"

    # Card / shape elements
    show_card: bool = False
    card_padding: int = 40
    card_corner_radius: int = 20
    card_opacity: float = 0.15

    # Decorative elements
    show_accent_line: bool = True
    accent_line_width: int = 4
    show_glow: bool = False
    glow_radius: int = 80


# Pre-defined templates
TEMPLATES: dict[VisualTemplate, TemplateConfig] = {
    VisualTemplate.DARK_GRADIENT: TemplateConfig(
        type=VisualTemplate.DARK_GRADIENT,
        name="Dark Gradient",
        bg_color_top=(10, 10, 20),
        bg_color_bottom=(20, 20, 40),
        use_gradient=True,
        hook_animation="scale_in",
        body_animation="slide_up",
        show_accent_line=True,
        show_card=False,
    ),

    VisualTemplate.NEON_CARD: TemplateConfig(
        type=VisualTemplate.NEON_CARD,
        name="Neon Card",
        bg_color_top=(8, 8, 18),
        bg_color_bottom=(12, 12, 28),
        use_gradient=True,
        hook_animation="slide_up",
        body_animation="fade_in",
        show_accent_line=False,
        show_card=True,
        card_opacity=0.12,
        show_glow=True,
        glow_radius=100,
        hook_y_ratio=0.30,
        body_y_ratio=0.42,
    ),

    VisualTemplate.SPLIT_SCREEN: TemplateConfig(
        type=VisualTemplate.SPLIT_SCREEN,
        name="Split Screen",
        bg_color_top=(15, 15, 30),
        bg_color_bottom=(10, 10, 20),
        use_gradient=True,
        hook_animation="slide_up",
        body_animation="slide_up",
        show_accent_line=True,
        accent_line_width=3,
        hook_y_ratio=0.25,
        body_y_ratio=0.50,
        caption_y_ratio=0.75,
    ),

    VisualTemplate.MINIMAL_CLEAN: TemplateConfig(
        type=VisualTemplate.MINIMAL_CLEAN,
        name="Minimal Clean",
        bg_color_top=(18, 18, 22),
        bg_color_bottom=(18, 18, 22),
        use_gradient=False,
        text_color=(240, 240, 245),
        hook_animation="fade_in",
        body_animation="fade_in",
        caption_animation="fade_in",
        show_accent_line=False,
        show_card=False,
        hook_font_size=68,
        body_font_size=42,
        hook_y_ratio=0.38,
        body_y_ratio=0.48,
    ),
}


def get_template(template_type: VisualTemplate) -> TemplateConfig:
    """Get a template configuration by type."""
    return TEMPLATES[template_type]


def get_all_template_types() -> list[str]:
    """Get all available template type values."""
    return [t.value for t in VisualTemplate]
