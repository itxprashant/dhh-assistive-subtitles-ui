from __future__ import annotations

import re
from collections.abc import MutableMapping


WORD_PATTERN = re.compile(r"\S+")


def ensure_stream_state(state: MutableMapping[str, object]) -> None:
    state.setdefault("caption_buffer", "")
    state.setdefault("stream_tokens", [])
    state.setdefault("stream_index", 0)
    state.setdefault("stream_transcript", "")
    state.setdefault("sim_playing", False)


def reset_stream(state: MutableMapping[str, object], transcript: str = "") -> None:
    """Reset simulated playback and clear the shared caption buffer."""

    state["caption_buffer"] = ""
    state["stream_tokens"] = tokenize_transcript(transcript)
    state["stream_index"] = 0
    state["stream_transcript"] = transcript
    state["sim_playing"] = False


def tokenize_transcript(transcript: str) -> list[str]:
    """Split transcript text into display tokens while preserving punctuation."""

    return WORD_PATTERN.findall(transcript.strip())


def advance_stream(
    state: MutableMapping[str, object],
    transcript: str,
    *,
    keep_history: bool,
    max_words: int,
) -> bool:
    """
    Add one word from the simulated transcript to the caption buffer.

    Returns True when playback has reached the end of the transcript.
    """

    ensure_stream_state(state)

    if state.get("stream_transcript") != transcript:
        state["stream_tokens"] = tokenize_transcript(transcript)
        state["stream_index"] = 0
        state["stream_transcript"] = transcript
        state["caption_buffer"] = ""

    tokens = state.get("stream_tokens", [])
    index = int(state.get("stream_index", 0))

    if not isinstance(tokens, list) or not tokens:
        state["caption_buffer"] = ""
        state["sim_playing"] = False
        return True

    if index >= len(tokens):
        state["sim_playing"] = False
        return True

    append_caption(
        state,
        str(tokens[index]),
        keep_history=keep_history,
        max_words=max_words,
    )
    state["stream_index"] = index + 1

    finished = index + 1 >= len(tokens)
    if finished:
        state["sim_playing"] = False
    return finished


def append_caption(
    state: MutableMapping[str, object],
    text: str,
    *,
    keep_history: bool,
    max_words: int,
) -> str:
    """Append or replace subtitle text in the shared caption buffer."""

    clean_text = " ".join(text.split())
    if not clean_text:
        return str(state.get("caption_buffer", ""))

    current = str(state.get("caption_buffer", "")).strip()
    combined = f"{current} {clean_text}".strip() if keep_history else clean_text
    trimmed = trim_to_words(combined, max_words=max_words)
    state["caption_buffer"] = trimmed
    return trimmed


def trim_to_words(text: str, *, max_words: int) -> str:
    words = WORD_PATTERN.findall(text.strip())
    if max_words <= 0 or len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[-max_words:])
