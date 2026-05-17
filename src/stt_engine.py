from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

from src.config import DEFAULT_STT_MODEL


TARGET_SAMPLE_RATE = 16_000
_MODEL_CACHE: dict[str, object] = {}
_MODEL_LOCK = threading.Lock()


class STTEngineUnavailable(RuntimeError):
    """Raised when the optional local speech-to-text engine cannot run."""


@dataclass(frozen=True)
class STTStatus:
    available: bool
    message: str


def get_stt_status() -> STTStatus:
    try:
        import faster_whisper  # noqa: F401
    except Exception as exc:  # pragma: no cover - depends on local environment
        return STTStatus(
            available=False,
            message=(
                "faster-whisper is not available yet. Install requirements and "
                f"restart Streamlit. Details: {exc}"
            ),
        )

    return STTStatus(
        available=True,
        message="Local STT is available. The first run may download the selected model.",
    )


def load_model(model_name: str = DEFAULT_STT_MODEL):
    """Load faster-whisper once per Python process.

    This avoids calling Streamlit cache APIs from the background audio thread,
    which can break live mic processing.
    """

    with _MODEL_LOCK:
        if model_name in _MODEL_CACHE:
            return _MODEL_CACHE[model_name]

        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # pragma: no cover - depends on local environment
            raise STTEngineUnavailable(
                "faster-whisper could not be imported. Run `pip install -r requirements.txt`."
            ) from exc

        try:
            model = WhisperModel(model_name, device="cpu", compute_type="int8")
        except Exception as exc:  # pragma: no cover - model download/runtime dependent
            raise STTEngineUnavailable(
                f"Could not load faster-whisper model '{model_name}': {exc}"
            ) from exc

        _MODEL_CACHE[model_name] = model
        return model


def transcribe_chunk(
    audio: np.ndarray,
    *,
    sample_rate: int,
    model_name: str = DEFAULT_STT_MODEL,
) -> str:
    """Transcribe a short PCM audio window with the cached local model."""

    if audio.size == 0:
        return ""

    waveform = normalize_audio(audio, sample_rate=sample_rate)
    if waveform.size == 0:
        return ""

    model = load_model(model_name)
    segments, _ = model.transcribe(
        waveform,
        language="en",
        beam_size=1,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
        condition_on_previous_text=False,
        no_speech_threshold=0.5,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


def normalize_audio(audio: np.ndarray, *, sample_rate: int) -> np.ndarray:
    """Convert arbitrary mono/stereo PCM data into 16 kHz float32 waveform."""

    arr = np.asarray(audio)
    if arr.ndim == 2:
        arr = arr.mean(axis=1)

    arr = arr.astype(np.float32, copy=False)
    max_abs = float(np.max(np.abs(arr))) if arr.size else 0.0
    if max_abs > 1.5:
        arr = arr / 32768.0

    if sample_rate != TARGET_SAMPLE_RATE and sample_rate > 0 and arr.size:
        if sample_rate % TARGET_SAMPLE_RATE == 0:
            # Integer decimation (e.g. 48 kHz -> 16 kHz). Average groups of N
            # samples to act as a basic anti-alias low-pass before downsampling.
            factor = sample_rate // TARGET_SAMPLE_RATE
            usable = (arr.size // factor) * factor
            if usable > 0:
                arr = arr[:usable].reshape(-1, factor).mean(axis=1)
            else:
                arr = arr[:0]
        else:
            duration = arr.size / sample_rate
            target_size = max(1, int(duration * TARGET_SAMPLE_RATE))
            source_x = np.linspace(0.0, duration, num=arr.size, endpoint=False)
            target_x = np.linspace(0.0, duration, num=target_size, endpoint=False)
            arr = np.interp(target_x, source_x, arr).astype(np.float32)

    return np.clip(arr, -1.0, 1.0).astype(np.float32, copy=False)
