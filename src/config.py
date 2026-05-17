from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CaptionPosition = Literal["bottom", "top"]


@dataclass(frozen=True)
class SubtitleStyle:
    """Visual settings shared by every subtitle input mode."""

    font_size: int = 44
    font_family: str = (
        "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    )
    text_color: str = "#ffffff"
    background_color: str = "#000000"
    background_opacity: float = 0.72
    position: CaptionPosition = "bottom"
    max_lines: int = 2
    keep_history: bool = True
    width_percent: int = 92
    vertical_offset: int = 32
    border_radius: int = 18
    line_height: float = 1.22


DEFAULT_WORDS_PER_SECOND = 3.0
DEFAULT_STT_MODEL = "tiny.en"
SUPPORTED_STT_MODELS = ("tiny.en", "base.en", "small.en")


def hex_to_rgba(hex_color: str, opacity: float) -> str:
    """Convert a #RRGGBB color and opacity to a CSS rgba() value."""

    normalized = hex_color.strip().lstrip("#")
    if len(normalized) != 6:
        return f"rgba(0, 0, 0, {opacity:.2f})"

    red = int(normalized[0:2], 16)
    green = int(normalized[2:4], 16)
    blue = int(normalized[4:6], 16)
    bounded_opacity = min(1.0, max(0.0, opacity))
    return f"rgba({red}, {green}, {blue}, {bounded_opacity:.2f})"
