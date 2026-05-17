from __future__ import annotations

import re
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from src.audio_capture import (
    WEBRTC_AVAILABLE,
    WEBRTC_ERROR,
    WebRtcMode,
    QueuedMicrophoneBuffer,
    drain_transcripts_to_caption_buffer,
    make_queued_audio_callback,
    start_transcription_worker,
    webrtc_streamer,
)
from src.config import (
    DEFAULT_STT_MODEL,
    SUPPORTED_STT_MODELS,
    SubtitleStyle,
)
from src.streaming import (
    ensure_stream_state,
    trim_to_words,
)
from src.stt_engine import get_stt_status
from src.subtitle_renderer import (
    image_file_to_data_url,
    render_band,
    render_overlay,
)


ROOT = Path(__file__).parent
SAMPLE_TRANSCRIPT = ROOT / "assets" / "sample_transcript.txt"
SAMPLE_SLIDE = ROOT / "assets" / "sample_slide.png"


def main() -> None:
    st.set_page_config(
        page_title="DHH Subtitle UI Prototype",
        page_icon="CC",
        layout="wide",
    )
    ensure_stream_state(st.session_state)

    st.title("Classroom Subtitle UI Prototype")
    st.caption(
        "A Streamlit mock for the floating subtitle band. "
        "Use the sidebar to switch input modes and tune the overlay."
    )

    mode, preview_mode, style, sim_settings, mic_settings, background_data_url = sidebar()
    max_words = max(10, style.max_lines * 14)
    sync_mode_state(mode, str(sim_settings.get("transcript", "")), max_words)

    with st.container():
        if mode == "Manual input":
            render_manual_mode(style=style, max_words=max_words)
        elif mode == "Simulated stream":
            render_simulated_mode(
                style=style,
                max_words=max_words,
                transcript=sim_settings["transcript"],
                seconds_per_subtitle=float(sim_settings["seconds_per_subtitle"]),
            )
        else:
            render_mic_mode(
                style=style,
                max_words=max_words,
                model_name=str(mic_settings["model_name"]),
            )

    st.divider()
    render_preview(
        preview_mode=preview_mode,
        style=style,
        background_data_url=background_data_url,
    )

    if mode == "Manual input" and st.session_state.get("manual_revealing"):
        time.sleep(float(st.session_state.get("manual_chunk_seconds", 1.8)))
        st.rerun()
    if mode == "Simulated stream" and st.session_state.get("sim_playing"):
        time.sleep(float(sim_settings["seconds_per_subtitle"]))
        st.rerun()
    if mode == "Live mic STT" and st.session_state.get("mic_should_poll"):
        time.sleep(1.0)
        st.rerun()


def sidebar() -> tuple[
    str,
    str,
    SubtitleStyle,
    dict[str, object],
    dict[str, object],
    str | None,
]:
    st.sidebar.header("Subtitle Controls")

    mode = st.sidebar.radio(
        "Input mode",
        ("Manual input", "Simulated stream", "Live mic STT"),
        key="mode",
    )

    preview_mode = st.sidebar.radio(
        "Preview",
        ("Band only", "Fullscreen overlay"),
        key="preview_mode",
    )

    with st.sidebar.expander("Style", expanded=True):
        font_size = st.slider("Font size", 24, 72, 44, step=2)
        text_color = st.color_picker("Text color", "#ffffff")
        background_color = st.color_picker("Band background", "#000000")
        background_opacity = st.slider("Background opacity", 0, 100, 72) / 100
        position = st.radio("Position", ("bottom", "top"), horizontal=True)
        max_lines = st.slider("Max visible lines", 1, 3, 2)
        keep_history = st.checkbox("Keep line history", value=True)
        vertical_offset = st.slider("Vertical offset", 12, 96, 32, step=4)

    style = SubtitleStyle(
        font_size=font_size,
        text_color=text_color,
        background_color=background_color,
        background_opacity=background_opacity,
        position=position,  # type: ignore[arg-type]
        max_lines=max_lines,
        keep_history=keep_history,
        vertical_offset=vertical_offset,
    )

    sim_settings = {"transcript": load_sample_transcript(), "seconds_per_subtitle": 1.8}
    if mode == "Simulated stream":
        with st.sidebar.expander("Simulation", expanded=True):
            sim_settings["seconds_per_subtitle"] = st.slider(
                "Seconds per subtitle",
                0.8,
                4.0,
                1.8,
                step=0.2,
                help="How long each simulated subtitle chunk stays on screen.",
            )
            sim_settings["transcript"] = st.text_area(
                "Transcript",
                value=load_sample_transcript(),
                height=180,
                key="sim_transcript",
            )
            col_a, col_b, col_c = st.columns(3)
            if col_a.button("Play", use_container_width=True):
                st.session_state["sim_playing"] = True
            if col_b.button("Pause", use_container_width=True):
                st.session_state["sim_playing"] = False
            if col_c.button("Reset", use_container_width=True):
                reset_simulated_stream(str(sim_settings["transcript"]))

    mic_settings = {"model_name": DEFAULT_STT_MODEL}
    if mode == "Live mic STT":
        with st.sidebar.expander("Local STT", expanded=True):
            mic_settings["model_name"] = st.selectbox(
                "Model",
                SUPPORTED_STT_MODELS,
                index=SUPPORTED_STT_MODELS.index(DEFAULT_STT_MODEL),
            )
            status = get_stt_status()
            if status.available:
                st.success(status.message)
            else:
                st.warning(status.message)
            if st.button("Clear live captions", use_container_width=True):
                st.session_state["caption_buffer"] = ""

    background_data_url = None
    if preview_mode == "Fullscreen overlay":
        with st.sidebar.expander("Overlay Background", expanded=True):
            uploaded_background = st.file_uploader(
                "Slide image",
                type=("png", "jpg", "jpeg", "webp"),
            )
            background_data_url = image_file_to_data_url(uploaded_background)
            if background_data_url is None:
                background_data_url = image_file_to_data_url(SAMPLE_SLIDE)
            st.caption("If no image is selected, the sample slide is used.")

    return mode, preview_mode, style, sim_settings, mic_settings, background_data_url


def render_manual_mode(*, style: SubtitleStyle, max_words: int) -> None:
    st.subheader("Manual Subtitle Input")
    st.session_state.setdefault("manual_text", "")
    st.session_state.setdefault("manual_chunk_seconds", 1.8)
    st.info(
        "Type a line, then press Ctrl+Enter or click Start captions. "
        "The text is shown as short readable subtitle chunks, not word-by-word. "
        f"History is {'on' if style.keep_history else 'off'} for stream and mic modes."
    )

    st.text_area(
        "Type or paste a caption line",
        placeholder="For example: Please open the thermodynamics slide and notice the response delay.",
        height=120,
        key="manual_text",
        on_change=start_manual_transition,
        args=(max_words,),
    )

    st.session_state["manual_chunk_seconds"] = st.slider(
        "Seconds per subtitle",
        0.8,
        4.0,
        float(st.session_state.get("manual_chunk_seconds", 1.8)),
        step=0.2,
        help="How long each readable subtitle chunk stays on screen.",
    )

    col_a, col_b, col_c = st.columns([1, 1, 1])
    if col_a.button("Start captions", use_container_width=True):
        start_manual_transition(max_words)
    if col_b.button("Show now", use_container_width=True):
        stop_manual_transition()
        sync_manual_caption(max_words)
    col_c.button("Clear", on_click=clear_manual_caption, use_container_width=True)

    if st.session_state.get("manual_revealing"):
        advance_manual_transition(max_words)
        total = len(st.session_state.get("manual_chunks", []))
        index = int(st.session_state.get("manual_index", 0))
        progress = 0.0 if total == 0 else min(1.0, index / total)
        st.progress(progress, text=f"{index} / {total} subtitle chunks shown")


def render_simulated_mode(
    *,
    style: SubtitleStyle,
    max_words: int,
    transcript: str,
    seconds_per_subtitle: float,
) -> None:
    st.subheader("Simulated Real-Time Stream")
    chunks = st.session_state.get("stream_chunks") or []
    index = int(st.session_state.get("stream_index", 0))
    total = len(chunks) if isinstance(chunks, list) else 0

    if st.session_state.get("stream_transcript") != transcript:
        reset_simulated_stream(transcript)
        chunks = st.session_state.get("stream_chunks") or []
        index = int(st.session_state.get("stream_index", 0))
        total = len(chunks) if isinstance(chunks, list) else 0

    if st.session_state.get("sim_playing"):
        if total > 0 and index >= total:
            reset_simulated_stream(transcript)
            st.session_state["sim_playing"] = True
        advance_simulated_stream(max_words)
        chunks = st.session_state.get("stream_chunks") or []
        index = int(st.session_state.get("stream_index", 0))
        total = len(chunks) if isinstance(chunks, list) else 0

    progress = 0.0 if total == 0 else min(1.0, index / total)
    st.progress(
        progress,
        text=f"{index} / {total} subtitle chunks shown ({seconds_per_subtitle:.1f}s each)",
    )
    st.caption("Use Play, Pause, and Reset in the sidebar. Transcript text is chunked into readable subtitle phrases.")


def render_mic_mode(*, style: SubtitleStyle, max_words: int, model_name: str) -> None:
    st.subheader("Live Microphone STT")
    st.session_state["mic_should_poll"] = False

    if not WEBRTC_AVAILABLE or webrtc_streamer is None or WebRtcMode is None:
        st.warning(
            "streamlit-webrtc is not available, so live microphone capture is disabled. "
            f"Install requirements and restart Streamlit. Details: {WEBRTC_ERROR}"
        )
        return

    st.caption(
        "Start the microphone stream below, allow browser mic permission, then speak "
        "clearly for a few seconds. The first run can pause while the local model loads."
    )

    mic_buffer = st.session_state.get("mic_buffer")
    if mic_buffer is None:
        mic_buffer = QueuedMicrophoneBuffer(window_seconds=4.0, overlap_seconds=0.6)
        st.session_state["mic_buffer"] = mic_buffer

    webrtc_ctx = webrtc_streamer(
        key="dhh-caption-mic-queued",
        mode=WebRtcMode.SENDONLY,
        queued_audio_frames_callback=make_queued_audio_callback(mic_buffer),
        media_stream_constraints={"audio": True, "video": False},
        async_processing=True,
        sendback_audio=False,
    )

    if not webrtc_ctx.state.playing:
        st.info("Microphone stream is stopped. Press Start and allow mic access.")
        return

    worker_signature = (id(mic_buffer), model_name)
    current_signature = st.session_state.get("stt_worker_signature")
    worker = st.session_state.get("stt_worker")

    if worker is None or current_signature != worker_signature or not worker.is_alive:
        stop_worker()
        st.session_state["stt_worker"] = start_transcription_worker(mic_buffer, model_name)
        st.session_state["stt_worker_signature"] = worker_signature
        worker = st.session_state["stt_worker"]

    transcripts = drain_transcripts_to_caption_buffer(
        worker,
        st.session_state,
        keep_history=style.keep_history,
        max_words=max_words,
    )
    for error in worker.drain_errors():
        st.warning(error)

    stats = worker.stats()
    cols = st.columns(4)
    cols[0].metric("Audio frames", int(stats.get("frames_seen", 0)))
    cols[1].metric("Queued windows", int(stats.get("windows_queued", 0)))
    cols[2].metric("Transcribed", int(stats.get("windows_transcribed", 0)))
    cols[3].metric("Dropped", int(stats.get("frames_dropped", 0)))

    peak = float(stats.get("last_peak", 0.0) or 0.0)
    rms = float(stats.get("last_rms", 0.0) or 0.0)
    sr = int(stats.get("sample_rate", 0) or 0)
    st.progress(min(1.0, peak), text=f"Mic level (peak {peak:.2f}, rms {rms:.3f}, {sr} Hz)")

    if transcripts:
        st.success(f"Latest transcript: {transcripts[-1]}")
    elif int(stats.get("frames_seen", 0)) == 0:
        st.info(
            "No audio frames yet. Check the browser mic permission and that the "
            "right input device is selected in your OS sound settings."
        )
    elif peak < 0.02:
        st.warning(
            "Mic is connected but the signal is very quiet. Speak closer to the "
            "mic or raise your input volume; Whisper needs audible speech."
        )
    elif int(stats.get("windows_transcribed", 0)) == 0:
        st.info("Listening. Speak for 3-4 seconds; captions appear after each audio window is processed.")
    else:
        st.info("Audio is being processed. No speech text detected in the latest window yet.")

    if webrtc_ctx.state.playing:
        st.session_state["mic_should_poll"] = True


def render_preview(
    *,
    preview_mode: str,
    style: SubtitleStyle,
    background_data_url: str | None,
) -> None:
    caption = str(st.session_state.get("caption_buffer", ""))
    previous = _track_caption_transition(caption)
    st.subheader("Preview")

    previous_text, leaving_text = previous
    if preview_mode == "Fullscreen overlay":
        components.html(
            render_overlay(
                caption,
                style,
                background_data_url,
                previous_text=previous_text,
                leaving_text=leaving_text,
            ),
            height=720,
            scrolling=False,
        )
    else:
        st.markdown(
            render_band(
                caption,
                style,
                previous_text=previous_text,
                leaving_text=leaving_text,
            ),
            unsafe_allow_html=True,
        )


def _track_caption_transition(current: str) -> tuple[str, str]:
    """Return (previous, leaving) caption text for the fade-up animation.

    Keeps a short rolling history so the dimmed previous line stays visible
    until a third caption arrives, at which point the oldest line gets the
    exit animation as the new one slides in.
    """

    history = list(st.session_state.get("_caption_history", []))
    current_norm = current.strip()

    if not current_norm:
        st.session_state["_caption_history"] = []
        return "", ""

    last = history[-1] if history else ""
    if current_norm != last:
        history.append(current_norm)
        history = history[-3:]
        st.session_state["_caption_history"] = history

    previous = history[-2] if len(history) >= 2 else ""
    leaving = history[-3] if len(history) >= 3 else ""
    return previous, leaving


def sync_mode_state(mode: str, transcript: str, max_words: int) -> None:
    """Keep shared caption state from leaking between input modes."""

    previous_mode = st.session_state.get("last_mode")
    if previous_mode == mode:
        return

    if previous_mode == "Live mic STT":
        stop_worker()

    st.session_state["sim_playing"] = False
    stop_manual_transition()

    if mode == "Manual input":
        st.session_state["caption_buffer"] = ""
    elif mode == "Simulated stream":
        reset_simulated_stream(transcript)
    else:
        st.session_state["caption_buffer"] = ""

    st.session_state["last_mode"] = mode


def stop_worker() -> None:
    worker = st.session_state.get("stt_worker")
    if worker is not None:
        worker.stop()
    st.session_state.pop("stt_worker", None)
    st.session_state.pop("stt_worker_signature", None)


def clear_manual_caption() -> None:
    stop_manual_transition()
    st.session_state["manual_text"] = ""
    st.session_state["caption_buffer"] = ""


def sync_manual_caption(max_words: int) -> None:
    st.session_state["caption_buffer"] = trim_to_words(
        str(st.session_state.get("manual_text", "")),
        max_words=max_words,
    )


def start_manual_transition(max_words: int) -> None:
    chunks = chunk_subtitle_text(
        str(st.session_state.get("manual_text", "")),
        max_words_per_chunk=min(max_words, 10),
    )
    st.session_state["manual_chunks"] = chunks
    st.session_state["manual_index"] = 0
    st.session_state["caption_buffer"] = ""
    st.session_state["manual_revealing"] = bool(chunks)


def stop_manual_transition() -> None:
    st.session_state["manual_revealing"] = False


def advance_manual_transition(max_words: int) -> None:
    chunks = st.session_state.get("manual_chunks", [])
    if not isinstance(chunks, list) or not chunks:
        stop_manual_transition()
        return

    index = int(st.session_state.get("manual_index", 0))
    if index >= len(chunks):
        stop_manual_transition()
        return

    next_index = index + 1
    st.session_state["caption_buffer"] = trim_to_words(
        str(chunks[index]),
        max_words=max_words,
    )
    st.session_state["manual_index"] = next_index

    if next_index >= len(chunks):
        stop_manual_transition()


def reset_simulated_stream(transcript: str) -> None:
    st.session_state["caption_buffer"] = ""
    st.session_state["stream_chunks"] = chunk_subtitle_text(
        transcript,
        max_words_per_chunk=10,
    )
    st.session_state["stream_index"] = 0
    st.session_state["stream_transcript"] = transcript
    st.session_state["sim_playing"] = False


def advance_simulated_stream(max_words: int) -> None:
    chunks = st.session_state.get("stream_chunks", [])
    if not isinstance(chunks, list) or not chunks:
        st.session_state["sim_playing"] = False
        return

    index = int(st.session_state.get("stream_index", 0))
    if index >= len(chunks):
        st.session_state["sim_playing"] = False
        return

    next_index = index + 1
    st.session_state["caption_buffer"] = trim_to_words(
        str(chunks[index]),
        max_words=max_words,
    )
    st.session_state["stream_index"] = next_index

    if next_index >= len(chunks):
        st.session_state["sim_playing"] = False


def chunk_subtitle_text(text: str, *, max_words_per_chunk: int = 10) -> list[str]:
    """Split text into calm, readable subtitle chunks."""

    normalized = " ".join(text.split())
    if not normalized:
        return []

    phrase_candidates = re.split(r"(?<=[.!?])\s+|(?<=[,;:])\s+", normalized)
    chunks: list[str] = []
    for phrase in phrase_candidates:
        words = phrase.split()
        if not words:
            continue
        for start in range(0, len(words), max_words_per_chunk):
            chunks.append(" ".join(words[start : start + max_words_per_chunk]))

    return chunks


@st.cache_data
def load_sample_transcript() -> str:
    if SAMPLE_TRANSCRIPT.exists():
        return SAMPLE_TRANSCRIPT.read_text(encoding="utf-8").strip()
    return (
        "Good morning everyone. Today we will test a classroom caption overlay "
        "that stays readable while the lecture slide remains visible."
    )


if __name__ == "__main__":
    main()
