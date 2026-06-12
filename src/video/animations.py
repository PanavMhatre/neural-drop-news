"""
Animation functions for video rendering.

Provides easing functions and animation utilities for text entrance,
exit, opacity, scaling, and other motion effects.
"""

import math
from typing import Callable


# ---------------------------------------------------------------------------
# Easing Functions: map t ∈ [0,1] → value ∈ [0,1]
# ---------------------------------------------------------------------------

def ease_linear(t: float) -> float:
    """Linear interpolation."""
    return max(0.0, min(1.0, t))


def ease_in_quad(t: float) -> float:
    """Quadratic ease-in — starts slow, accelerates."""
    t = max(0.0, min(1.0, t))
    return t * t


def ease_out_quad(t: float) -> float:
    """Quadratic ease-out — starts fast, decelerates."""
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) * (1 - t)


def ease_in_out_quad(t: float) -> float:
    """Quadratic ease-in-out — smooth start and end."""
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return 2 * t * t
    return 1 - pow(-2 * t + 2, 2) / 2


def ease_in_cubic(t: float) -> float:
    """Cubic ease-in."""
    t = max(0.0, min(1.0, t))
    return t * t * t


def ease_out_cubic(t: float) -> float:
    """Cubic ease-out — smooth deceleration."""
    t = max(0.0, min(1.0, t))
    return 1 - pow(1 - t, 3)


def ease_in_out_cubic(t: float) -> float:
    """Cubic ease-in-out — very smooth."""
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return 4 * t * t * t
    return 1 - pow(-2 * t + 2, 3) / 2


def ease_out_bounce(t: float) -> float:
    """Bounce ease-out — bouncy landing."""
    t = max(0.0, min(1.0, t))
    n1 = 7.5625
    d1 = 2.75
    if t < 1 / d1:
        return n1 * t * t
    elif t < 2 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    elif t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    else:
        t -= 2.625 / d1
        return n1 * t * t + 0.984375


def ease_out_elastic(t: float) -> float:
    """Elastic ease-out — springy overshoot."""
    t = max(0.0, min(1.0, t))
    if t == 0 or t == 1:
        return t
    c4 = (2 * math.pi) / 3
    return pow(2, -10 * t) * math.sin((t * 10 - 0.75) * c4) + 1


def ease_out_back(t: float) -> float:
    """Back ease-out — slight overshoot."""
    t = max(0.0, min(1.0, t))
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


# ---------------------------------------------------------------------------
# Animation Helpers
# ---------------------------------------------------------------------------

def interpolate(start: float, end: float, t: float, easing: Callable = ease_out_cubic) -> float:
    """Interpolate between two values with easing."""
    eased_t = easing(t)
    return start + (end - start) * eased_t


def fade_in(
    frame_time: float,
    start_time: float,
    duration: float = 0.3,
) -> float:
    """Calculate opacity for a fade-in effect (0.0 → 1.0)."""
    if frame_time < start_time:
        return 0.0
    elapsed = frame_time - start_time
    if elapsed >= duration:
        return 1.0
    return ease_out_cubic(elapsed / duration)


def fade_out(
    frame_time: float,
    end_time: float,
    duration: float = 0.3,
) -> float:
    """Calculate opacity for a fade-out effect (1.0 → 0.0)."""
    time_to_end = end_time - frame_time
    if time_to_end <= 0:
        return 0.0
    if time_to_end >= duration:
        return 1.0
    return ease_out_cubic(time_to_end / duration)


def slide_up(
    frame_time: float,
    start_time: float,
    target_y: float,
    offset: float = 80,
    duration: float = 0.4,
) -> float:
    """Calculate Y position for slide-up entrance."""
    if frame_time < start_time:
        return target_y + offset
    elapsed = frame_time - start_time
    if elapsed >= duration:
        return target_y
    return interpolate(target_y + offset, target_y, elapsed / duration, ease_out_cubic)


def slide_down(
    frame_time: float,
    start_time: float,
    target_y: float,
    offset: float = 80,
    duration: float = 0.4,
) -> float:
    """Calculate Y position for slide-down entrance."""
    if frame_time < start_time:
        return target_y - offset
    elapsed = frame_time - start_time
    if elapsed >= duration:
        return target_y
    return interpolate(target_y - offset, target_y, elapsed / duration, ease_out_cubic)


def scale_in(
    frame_time: float,
    start_time: float,
    duration: float = 0.3,
    start_scale: float = 0.5,
) -> float:
    """Calculate scale factor for scale-in effect."""
    if frame_time < start_time:
        return start_scale
    elapsed = frame_time - start_time
    if elapsed >= duration:
        return 1.0
    return interpolate(start_scale, 1.0, elapsed / duration, ease_out_back)


def pulse(
    frame_time: float,
    frequency: float = 2.0,
    amplitude: float = 0.05,
) -> float:
    """Gentle pulsing scale effect."""
    return 1.0 + amplitude * math.sin(frame_time * frequency * 2 * math.pi)


def typewriter_progress(
    frame_time: float,
    start_time: float,
    text_length: int,
    chars_per_second: float = 30,
) -> int:
    """Calculate how many characters to show for typewriter effect."""
    if frame_time < start_time:
        return 0
    elapsed = frame_time - start_time
    chars = int(elapsed * chars_per_second)
    return min(chars, text_length)


def progress_bar_value(
    frame_time: float,
    total_duration: float,
) -> float:
    """Calculate progress bar fill (0.0 → 1.0)."""
    if total_duration <= 0:
        return 0.0
    return max(0.0, min(1.0, frame_time / total_duration))
