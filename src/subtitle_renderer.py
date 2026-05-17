from __future__ import annotations

import base64
import html
import mimetypes
from pathlib import Path
from typing import BinaryIO

from src.config import SubtitleStyle, hex_to_rgba


EMPTY_CAPTION = "Captions will appear here"


def render_band(
    text: str,
    style: SubtitleStyle,
    *,
    previous_text: str = "",
    leaving_text: str = "",
) -> str:
    """Return HTML for the in-page subtitle band preview."""

    caption = _caption_text(text)
    anchor_rule = _anchor_rule(style)
    background = hex_to_rgba(style.background_color, style.background_opacity)
    is_empty = not text.strip()
    muted_class = " is-empty" if is_empty else ""
    previous_html, leaving_html = _history_lines_html(
        text, previous_text, leaving_text, hidden=is_empty
    )

    return f"""
<style>
    .caption-preview-frame {{
        position: relative;
        min-height: 280px;
        overflow: hidden;
        border-radius: 22px;
        border: 1px solid rgba(148, 163, 184, 0.28);
        background:
            radial-gradient(circle at 20% 18%, rgba(59, 130, 246, 0.24), transparent 26%),
            linear-gradient(135deg, #111827 0%, #1f2937 45%, #020617 100%);
        box-shadow: inset 0 0 0 1px rgba(255,255,255,0.04);
    }}
    .caption-preview-title {{
        position: absolute;
        top: 24px;
        left: 32px;
        max-width: 58%;
        color: rgba(226, 232, 240, 0.78);
        font-family: {style.font_family};
        font-size: 22px;
        line-height: 1.35;
    }}
    .subtitle-band {{
        position: absolute;
        {anchor_rule}
        left: 50%;
        transform: translateX(-50%);
        width: {style.width_percent}%;
        box-sizing: border-box;
        padding: 16px 26px;
        border-radius: {style.border_radius}px;
        background: {background};
        color: {style.text_color};
        font-family: {style.font_family};
        font-size: {style.font_size}px;
        font-weight: 700;
        line-height: {style.line_height};
        letter-spacing: 0.01em;
        text-align: center;
        text-shadow: 0 2px 6px rgba(0,0,0,0.72);
        box-shadow: 0 18px 56px rgba(0, 0, 0, 0.28);
        backdrop-filter: blur(10px);
    }}
    {_caption_stack_css(style)}
    .subtitle-band.is-empty {{
        color: rgba(255,255,255,0.62);
        font-style: italic;
        font-weight: 500;
    }}
</style>
<div class="caption-preview-frame">
    <div class="caption-preview-title">
        Subtitle band preview<br>
        Tuned for projector visibility and low visual interruption.
    </div>
    <div class="subtitle-band{muted_class}">
        <div class="subtitle-text">{leaving_html}{previous_html}<span class="caption-line is-current">{caption}</span></div>
    </div>
</div>
"""


def render_overlay(
    text: str,
    style: SubtitleStyle,
    background_data_url: str | None = None,
    *,
    previous_text: str = "",
    leaving_text: str = "",
) -> str:
    """Return a full-screen HTML mock that resembles an HDMI subtitle overlay."""

    caption = _caption_text(text)
    anchor_rule = _anchor_rule(style)
    background = hex_to_rgba(style.background_color, style.background_opacity)
    is_empty = not text.strip()
    muted_class = " is-empty" if is_empty else ""
    previous_html, leaving_html = _history_lines_html(
        text, previous_text, leaving_text, hidden=is_empty
    )
    background_rule = (
        f"background-image: url('{background_data_url}');"
        if background_data_url
        else _fallback_slide_background()
    )
    slide_content = "" if background_data_url else _fallback_slide_content()

    return f"""
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        html, body {{
            margin: 0;
            width: 100%;
            height: 100%;
            overflow: hidden;
            background: #020617;
        }}
        .projector-canvas {{
            position: fixed;
            inset: 0;
            overflow: hidden;
            background-color: #f8fafc;
            background-position: center;
            background-repeat: no-repeat;
            background-size: contain;
            {background_rule}
            font-family: {style.font_family};
        }}
        .projector-canvas::after {{
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            background: linear-gradient(
                to bottom,
                rgba(15, 23, 42, 0.08),
                transparent 28%,
                transparent 68%,
                rgba(15, 23, 42, 0.14)
            );
        }}
        .overlay-subtitle {{
            position: fixed;
            {anchor_rule}
            left: 50%;
            transform: translateX(-50%);
            z-index: 2;
            width: {style.width_percent}%;
            box-sizing: border-box;
            padding: 16px 28px;
            border-radius: {style.border_radius}px;
            background: {background};
            color: {style.text_color};
            font-family: {style.font_family};
            font-size: {style.font_size}px;
            font-weight: 750;
            line-height: {style.line_height};
            letter-spacing: 0.01em;
            text-align: center;
            text-shadow: 0 2px 7px rgba(0,0,0,0.82);
            box-shadow: 0 18px 60px rgba(0, 0, 0, 0.32);
            backdrop-filter: blur(12px);
        }}
        {_caption_stack_css(style, scope=".overlay-subtitle-text")}
        .overlay-subtitle.is-empty {{
            color: rgba(255,255,255,0.62);
            font-style: italic;
            font-weight: 500;
        }}
        .preview-label {{
            position: fixed;
            top: 20px;
            right: 24px;
            z-index: 3;
            padding: 8px 12px;
            border-radius: 999px;
            background: rgba(15, 23, 42, 0.74);
            color: rgba(255,255,255,0.82);
            font: 600 14px {style.font_family};
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }}
    </style>
</head>
<body>
    <main class="projector-canvas">{slide_content}</main>
    <div class="preview-label">Overlay preview</div>
    <div class="overlay-subtitle{muted_class}">
        <div class="overlay-subtitle-text">{leaving_html}{previous_html}<span class="caption-line is-current">{caption}</span></div>
    </div>
</body>
</html>
"""


def image_file_to_data_url(file: BinaryIO | bytes | Path | str | None) -> str | None:
    """Encode an uploaded file or local image path as a browser-friendly data URL."""

    if file is None:
        return None

    mime_type = "image/png"
    data: bytes

    if isinstance(file, (str, Path)):
        path = Path(file)
        if not path.exists():
            return None
        data = path.read_bytes()
        mime_type = mimetypes.guess_type(path.name)[0] or mime_type
    elif isinstance(file, bytes):
        data = file
    else:
        if hasattr(file, "getvalue"):
            data = file.getvalue()
        else:
            data = file.read()
        name = getattr(file, "name", "")
        mime_type = getattr(file, "type", None) or mimetypes.guess_type(name)[0] or mime_type

    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _caption_text(text: str) -> str:
    return html.escape(text.strip() or EMPTY_CAPTION)


def _history_lines_html(
    current: str,
    previous: str,
    leaving: str,
    *,
    hidden: bool,
) -> tuple[str, str]:
    """Render the dimmed previous line and the outgoing leaving line."""

    if hidden:
        return "", ""

    current_norm = current.strip()
    previous_norm = previous.strip()
    leaving_norm = leaving.strip()

    previous_html = ""
    if previous_norm and previous_norm != current_norm:
        previous_html = (
            f'<span class="caption-line is-previous">'
            f'{html.escape(previous_norm)}</span>'
        )

    leaving_html = ""
    if (
        leaving_norm
        and leaving_norm != current_norm
        and leaving_norm != previous_norm
    ):
        leaving_html = (
            f'<span class="caption-line is-leaving">'
            f'{html.escape(leaving_norm)}</span>'
        )

    return previous_html, leaving_html


def _caption_stack_css(style: SubtitleStyle, *, scope: str = ".subtitle-text") -> str:
    """Shared CSS for the Spotify-style fade-up caption stack."""

    height_rule = f"calc({style.max_lines} * {style.line_height}em)"
    line_rule = f"{style.line_height}em"
    return f"""
    {scope} {{
        position: relative;
        display: flex;
        flex-direction: column;
        justify-content: flex-end;
        min-height: {height_rule};
        max-height: {height_rule};
        overflow: hidden;
        text-align: center;
    }}
    {scope} .caption-line {{
        display: block;
        width: 100%;
        word-break: break-word;
        will-change: transform, opacity, filter;
        transform-origin: center bottom;
    }}
    {scope} .caption-line.is-current {{
        opacity: 1;
        animation: caption-rise-in 480ms cubic-bezier(0.22, 1, 0.36, 1) both;
    }}
    {scope} .caption-line.is-previous {{
        opacity: 0.42;
        animation: caption-rise-in 520ms cubic-bezier(0.22, 1, 0.36, 1) both;
    }}
    {scope} .caption-line.is-leaving {{
        position: absolute;
        left: 0;
        right: 0;
        bottom: {line_rule};
        opacity: 0;
        pointer-events: none;
        animation: caption-rise-out 560ms cubic-bezier(0.4, 0, 0.2, 1) forwards;
    }}
    @keyframes caption-rise-in {{
        0%   {{ opacity: 0; transform: translateY(95%); filter: blur(2px); }}
        55%  {{ filter: blur(0); }}
        100% {{ transform: translateY(0); filter: blur(0); }}
    }}
    @keyframes caption-rise-out {{
        0%   {{ opacity: 0.42; transform: translateY(0); filter: blur(0); }}
        100% {{ opacity: 0; transform: translateY(-110%); filter: blur(3px); }}
    }}
    """


def _anchor_rule(style: SubtitleStyle) -> str:
    return f"{style.position}: {style.vertical_offset}px;"


def _fallback_slide_background() -> str:
    return """
            background:
                radial-gradient(circle at 12% 18%, rgba(37, 99, 235, 0.16), transparent 24%),
                linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
    """


def _fallback_slide_content() -> str:
    return """
        <section style="padding: 8vh 8vw; color: #0f172a;">
            <div style="font-size: clamp(34px, 5vw, 74px); font-weight: 800; max-width: 900px; line-height: 1.04;">
                Accessible Classroom Captions
            </div>
            <p style="font-size: clamp(20px, 2.1vw, 34px); max-width: 760px; line-height: 1.35; color: #334155;">
                A local subtitle overlay that sits on top of existing lecture slides without changing how instructors teach.
            </p>
            <div style="margin-top: 7vh; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 24px; max-width: 980px;">
                <div style="background: rgba(255,255,255,0.72); border-radius: 24px; padding: 24px; box-shadow: 0 18px 50px rgba(15,23,42,0.12);">
                    <strong style="font-size: 28px;">Local</strong><br>
                    <span style="font-size: 21px; color: #475569;">No cloud dependency</span>
                </div>
                <div style="background: rgba(255,255,255,0.72); border-radius: 24px; padding: 24px; box-shadow: 0 18px 50px rgba(15,23,42,0.12);">
                    <strong style="font-size: 28px;">Fast</strong><br>
                    <span style="font-size: 21px; color: #475569;">Low-latency feedback</span>
                </div>
                <div style="background: rgba(255,255,255,0.72); border-radius: 24px; padding: 24px; box-shadow: 0 18px 50px rgba(15,23,42,0.12);">
                    <strong style="font-size: 28px;">Native</strong><br>
                    <span style="font-size: 21px; color: #475569;">Projector overlay</span>
                </div>
            </div>
        </section>
    """
