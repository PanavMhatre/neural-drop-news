"""
Motion graphics — generates short animated video clips using PIL + FFmpeg.

Produces a 9:16 animated background (price chart draw-on, data bars, animated
stats). Not currently called from SmartBRollAgent (b-roll is YouTube-only —
no stock-footage or synthetic fallback), but kept as a standalone utility.
"""

import math
import subprocess
import tempfile
import logging
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# 9:16 vertical dimensions
WIDTH = 1080
HEIGHT = 1920
FPS = 30


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _ease_in_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------------------
# Animated price chart generator
# ---------------------------------------------------------------------------

def _generate_price_chart_frame(
    frame: int,
    total_frames: int,
    accent_color: tuple,
    title: str,
    values: list[float],
    is_up: bool,
) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), color=(8, 10, 18))
    draw = ImageDraw.Draw(img)

    # Subtle grid lines
    for i in range(1, 5):
        y = int(HEIGHT * 0.2 + i * HEIGHT * 0.5 / 5)
        draw.line([(60, y), (WIDTH - 60, y)], fill=(30, 35, 50), width=1)

    chart_x0 = 80
    chart_x1 = WIDTH - 80
    chart_y0 = int(HEIGHT * 0.25)
    chart_y1 = int(HEIGHT * 0.70)
    chart_w = chart_x1 - chart_x0
    chart_h = chart_y1 - chart_y0

    n = len(values)
    v_min = min(values) * 0.995
    v_max = max(values) * 1.005
    v_range = max(v_max - v_min, 0.0001)

    def _to_px(i_: int, v_: float) -> tuple[int, int]:
        x = chart_x0 + int(i_ / (n - 1) * chart_w)
        y = chart_y1 - int((v_ - v_min) / v_range * chart_h)
        return x, y

    # Animate draw-on progress
    progress = _ease_out_cubic(frame / max(total_frames - 1, 1))
    draw_to = max(2, int(progress * n))

    # Draw filled area
    if draw_to >= 2:
        poly_pts = [_to_px(i, values[i]) for i in range(draw_to)]
        last_x, _ = poly_pts[-1]
        poly_pts += [(last_x, chart_y1), (chart_x0, chart_y1)]
        fill_color = (*accent_color, 40) if len(accent_color) == 3 else accent_color
        img_a = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        draw_a = ImageDraw.Draw(img_a)
        draw_a.polygon(poly_pts, fill=(*accent_color, 35))
        img.paste(Image.alpha_composite(img.convert("RGBA"), img_a).convert("RGB"))
        draw = ImageDraw.Draw(img)

    # Draw line
    if draw_to >= 2:
        pts = [_to_px(i, values[i]) for i in range(draw_to)]
        for j in range(len(pts) - 1):
            draw.line([pts[j], pts[j + 1]], fill=accent_color, width=4)

    # Glowing dot at current position
    if draw_to >= 2:
        cx, cy = _to_px(draw_to - 1, values[draw_to - 1])
        pulse = 1.0 + 0.2 * math.sin(frame * 0.3)
        r = int(10 * pulse)
        for layer in [(r + 8, (*accent_color, 30)), (r + 4, (*accent_color, 60)), (r, (*accent_color, 255))]:
            lr, lc = layer
            img_g = img.convert("RGBA")
            draw_g = ImageDraw.Draw(img_g)
            draw_g.ellipse([cx - lr, cy - lr, cx + lr, cy + lr], fill=lc)
            img = img_g.convert("RGB")
        draw = ImageDraw.Draw(img)

    # Title at top
    font_title = _get_font(56)
    font_sub = _get_font(38)
    font_val = _get_font(80)

    title_alpha = _ease_out_cubic(min(1.0, frame / (FPS * 0.4)))
    # Draw title
    try:
        bbox = draw.textbbox((0, 0), title[:40], font=font_title)
        tw = bbox[2] - bbox[0]
        draw.text(((WIDTH - tw) // 2, int(HEIGHT * 0.08)), title[:40], font=font_title, fill=(220, 220, 240))
    except Exception:
        draw.text((80, int(HEIGHT * 0.08)), title[:40], font=font_title, fill=(220, 220, 240))

    # Current value + change
    if draw_to >= 2:
        cur_val = values[draw_to - 1]
        pct_change = (values[draw_to - 1] - values[0]) / values[0] * 100
        sign = "▲" if is_up else "▼"
        clr = (80, 220, 120) if is_up else (220, 80, 80)
        val_str = f"${cur_val:,.0f}" if cur_val > 100 else f"${cur_val:.4f}"
        pct_str = f"{sign} {abs(pct_change):.1f}%"
        try:
            bbox_v = draw.textbbox((0, 0), val_str, font=font_val)
            vw = bbox_v[2] - bbox_v[0]
            draw.text(((WIDTH - vw) // 2, int(HEIGHT * 0.73)), val_str, font=font_val, fill=(255, 255, 255))
            bbox_p = draw.textbbox((0, 0), pct_str, font=font_sub)
            pw = bbox_p[2] - bbox_p[0]
            draw.text(((WIDTH - pw) // 2, int(HEIGHT * 0.82)), pct_str, font=font_sub, fill=clr)
        except Exception:
            draw.text((80, int(HEIGHT * 0.73)), val_str, font=font_val, fill=(255, 255, 255))

    return img


def _extract_price_data(story_title: str) -> tuple[list[float], bool]:
    """Generate plausible BTC/crypto price data from story context."""
    import random
    import hashlib

    seed = int(hashlib.md5(story_title.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    title_lower = story_title.lower()
    is_up = any(w in title_lower for w in ["surge", "rise", "bull", "rally", "gain", "high", "record", "etf"])
    is_down = any(w in title_lower for w in ["drop", "fall", "crash", "bear", "low", "dump", "sell"])

    if "bitcoin" in title_lower or "btc" in title_lower:
        base = rng.uniform(60000, 105000)
    elif "ethereum" in title_lower or "eth" in title_lower:
        base = rng.uniform(2000, 4500)
    elif "solana" in title_lower or "sol" in title_lower:
        base = rng.uniform(80, 250)
    else:
        base = rng.uniform(1, 100)

    direction = 1 if is_up else (-1 if is_down else rng.choice([-1, 1]))
    n = 50
    values = [base]
    for _ in range(n - 1):
        drift = direction * rng.uniform(0.002, 0.008)
        noise = rng.gauss(0, 0.005)
        values.append(values[-1] * (1 + drift + noise))

    return values, values[-1] > values[0]


def generate_animated_chart(
    output_path: str,
    story_title: str,
    accent_color: tuple,
    duration: float = 8.0,
) -> bool:
    """
    Render an animated price chart to MP4. Returns True on success.
    Output is 1080×1920 (9:16) at 30fps.
    """
    values, is_up = _extract_price_data(story_title)
    total_frames = int(duration * FPS)

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{WIDTH}x{HEIGHT}",
        "-pix_fmt", "rgb24",
        "-r", str(FPS),
        "-i", "-",
        "-c:v", "libx264", "-preset", "faster", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an",
        output_path,
    ]

    try:
        proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for f in range(total_frames):
            frame_img = _generate_price_chart_frame(f, total_frames, accent_color,
                                                     story_title, values, is_up)
            proc.stdin.write(frame_img.tobytes())
        proc.stdin.close()
        proc.wait(timeout=120)
        if proc.returncode != 0:
            logger.error(f"Motion graphics ffmpeg failed: {proc.returncode}")
            return False
        logger.info(f"Motion graphics chart generated: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Motion graphics generation failed: {e}")
        if "proc" in dir() and proc.poll() is None:
            proc.kill()
        return False


# ---------------------------------------------------------------------------
# Animated bar chart (for non-price stories)
# ---------------------------------------------------------------------------

def generate_animated_bars(
    output_path: str,
    story_title: str,
    accent_color: tuple,
    duration: float = 8.0,
) -> bool:
    """Render an animated bar chart (e.g. market cap comparison)."""
    import random
    import hashlib

    seed = int(hashlib.md5(story_title.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    labels = ["BTC", "ETH", "SOL", "BNB", "XRP"]
    values_raw = [rng.uniform(0.4, 1.0) for _ in labels]
    max_v = max(values_raw)
    values_norm = [v / max_v for v in values_raw]

    total_frames = int(duration * FPS)
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{WIDTH}x{HEIGHT}",
        "-pix_fmt", "rgb24",
        "-r", str(FPS),
        "-i", "-",
        "-c:v", "libx264", "-preset", "faster", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an",
        output_path,
    ]

    font_lbl = _get_font(44)
    font_title = _get_font(54)

    bar_x0 = 120
    bar_x1 = WIDTH - 120
    bar_y0 = int(HEIGHT * 0.25)
    bar_gap = 120
    bar_h = 80

    try:
        proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for f in range(total_frames):
            img = Image.new("RGB", (WIDTH, HEIGHT), color=(8, 10, 18))
            draw = ImageDraw.Draw(img)

            progress = _ease_out_cubic(min(1.0, f / (FPS * 1.5)))

            # Title
            try:
                bbox = draw.textbbox((0, 0), "Market Dominance", font=font_title)
                tw = bbox[2] - bbox[0]
                draw.text(((WIDTH - tw) // 2, int(HEIGHT * 0.08)), "Market Dominance",
                          font=font_title, fill=(220, 220, 240))
            except Exception:
                draw.text((80, int(HEIGHT * 0.08)), "Market Dominance", font=font_title, fill=(220, 220, 240))

            for i, (label, v_norm) in enumerate(zip(labels, values_norm)):
                bar_y = bar_y0 + i * (bar_h + bar_gap)
                max_w = bar_x1 - bar_x0
                cur_w = int(v_norm * max_w * progress)
                # Background track
                draw.rounded_rectangle([bar_x0, bar_y, bar_x1, bar_y + bar_h],
                                        radius=8, fill=(25, 30, 45))
                # Filled bar
                if cur_w > 10:
                    alpha = min(1.0, progress * 2)
                    fill = tuple(int(c * alpha + 25 * (1 - alpha)) for c in accent_color)
                    draw.rounded_rectangle([bar_x0, bar_y, bar_x0 + cur_w, bar_y + bar_h],
                                            radius=8, fill=fill)
                # Label
                draw.text((bar_x0, bar_y - 35), label, font=font_lbl, fill=(180, 185, 210))

            proc.stdin.write(img.tobytes())

        proc.stdin.close()
        proc.wait(timeout=120)
        return proc.returncode == 0
    except Exception as e:
        logger.error(f"Animated bars generation failed: {e}")
        return False


def generate_for_section(
    output_path: str,
    story_title: str,
    section: str,
    accent_color: tuple,
    duration: float = 8.0,
) -> bool:
    """Pick the best motion graphic style for the section and story."""
    title_lower = story_title.lower()
    price_keywords = ["price", "bitcoin", "btc", "eth", "ethereum", "solana", "sol",
                      "crash", "surge", "rally", "drop", "all-time", "high", "low"]
    use_chart = any(kw in title_lower for kw in price_keywords) or section in ("hook", "explanation")

    if use_chart:
        return generate_animated_chart(output_path, story_title, accent_color, duration)
    else:
        return generate_animated_bars(output_path, story_title, accent_color, duration)
