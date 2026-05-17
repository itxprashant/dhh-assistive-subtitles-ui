from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from src.stt_engine import STTEngineUnavailable, transcribe_chunk
from src.streaming import append_caption

try:  # Optional until the user installs requirements.
    from streamlit_webrtc import AudioProcessorBase, WebRtcMode, webrtc_streamer

    WEBRTC_AVAILABLE = True
    WEBRTC_ERROR = ""
except Exception as exc:  # pragma: no cover - depends on local environment
    AudioProcessorBase = object  # type: ignore[assignment,misc]
    WebRtcMode = None  # type: ignore[assignment]
    webrtc_streamer = None  # type: ignore[assignment]
    WEBRTC_AVAILABLE = False
    WEBRTC_ERROR = str(exc)


@dataclass(frozen=True)
class AudioWindow:
    samples: np.ndarray
    sample_rate: int


def _frame_to_mono_float32(frame: Any) -> np.ndarray:
    """Extract a mono float32 waveform (1D, range ~[-1, 1]) from a PyAV frame.

    Browsers/aiortc usually deliver packed ``s16`` stereo at 48 kHz. PyAV's
    ``to_ndarray()`` then returns interleaved data with shape
    ``(1, nb_samples * channels)``. We must deinterleave and downmix to mono
    so the sample count and pitch fed to Whisper are correct.
    """

    layout = getattr(frame, "layout", None)
    channels = 1
    try:
        if layout is not None:
            channels = max(1, len(layout.channels))
    except Exception:
        channels = 1

    fmt = getattr(frame, "format", None)
    is_planar = bool(getattr(fmt, "is_planar", False)) if fmt is not None else False

    raw = frame.to_ndarray()

    if raw.ndim == 1:
        flat = raw
        if channels > 1 and flat.size % channels == 0:
            mono = flat.reshape(-1, channels).mean(axis=1)
        else:
            mono = flat
    elif raw.ndim == 2:
        if is_planar or (raw.shape[0] == channels and raw.shape[0] > 1):
            mono = raw.mean(axis=0) if raw.shape[0] > 1 else raw[0]
        elif raw.shape[0] == 1:
            flat = raw.reshape(-1)
            if channels > 1 and flat.size % channels == 0:
                mono = flat.reshape(-1, channels).mean(axis=1)
            else:
                mono = flat
        else:
            mono = raw.mean(axis=1) if raw.shape[1] in (1, 2, 4, 6, 8) else raw[:, 0]
    else:
        mono = raw.reshape(-1)

    mono = np.asarray(mono)
    if np.issubdtype(mono.dtype, np.integer):
        info = np.iinfo(mono.dtype)
        denom = float(max(abs(int(info.min)), int(info.max))) or 1.0
        mono = mono.astype(np.float32) / denom
    else:
        mono = mono.astype(np.float32, copy=False)

    return mono


class QueuedMicrophoneBuffer:
    """Collect queued WebRTC microphone frames into transcription windows."""

    def __init__(
        self,
        window_seconds: float = 4.0,
        overlap_seconds: float = 0.6,
    ) -> None:
        self.window_seconds = window_seconds
        self.overlap_seconds = max(0.0, min(overlap_seconds, window_seconds * 0.5))
        self.audio_queue: queue.Queue[AudioWindow] = queue.Queue(maxsize=4)
        self._chunks: list[np.ndarray] = []
        self._sample_count = 0
        self._sample_rate = 0
        self._lock = threading.Lock()
        self.frames_seen = 0
        self.windows_queued = 0
        self.frames_dropped = 0
        self.last_peak = 0.0
        self.last_rms = 0.0

    def add_frame(self, frame: Any) -> None:
        sample_rate = int(getattr(frame, "sample_rate", 48_000) or 48_000)
        mono = _frame_to_mono_float32(frame)
        if mono.size == 0:
            return

        peak = float(np.max(np.abs(mono))) if mono.size else 0.0
        rms = float(np.sqrt(np.mean(mono.astype(np.float32) ** 2))) if mono.size else 0.0

        with self._lock:
            self.frames_seen += 1
            self._sample_rate = sample_rate
            self.last_peak = peak
            self.last_rms = rms
            self._chunks.append(mono)
            self._sample_count += int(mono.shape[0])
            target_samples = int(sample_rate * self.window_seconds)

            if self._sample_count >= target_samples:
                window = np.concatenate(self._chunks, axis=0).astype(
                    np.float32, copy=False
                )

                # Keep a small tail so phrases spanning window boundaries are
                # not chopped between transcriptions.
                overlap_samples = int(sample_rate * self.overlap_seconds)
                if overlap_samples > 0 and window.shape[0] > overlap_samples:
                    tail = window[-overlap_samples:]
                    self._chunks = [tail]
                    self._sample_count = int(tail.shape[0])
                else:
                    self._chunks = []
                    self._sample_count = 0

                self._put_window(AudioWindow(samples=window, sample_rate=sample_rate))

    def _put_window(self, window: AudioWindow) -> None:
        try:
            self.audio_queue.put_nowait(window)
            self.windows_queued += 1
        except queue.Full:
            try:
                self.audio_queue.get_nowait()
                self.frames_dropped += 1
            except queue.Empty:
                pass
            self.audio_queue.put_nowait(window)
            self.windows_queued += 1

    def stats(self) -> dict[str, object]:
        with self._lock:
            return {
                "frames_seen": self.frames_seen,
                "windows_queued": self.windows_queued,
                "frames_dropped": self.frames_dropped,
                "pending_windows": self.audio_queue.qsize(),
                "last_peak": self.last_peak,
                "last_rms": self.last_rms,
                "sample_rate": self._sample_rate,
            }


class MicrophoneAudioProcessor(AudioProcessorBase):  # type: ignore[misc,valid-type]
    """Compatibility processor for older streamlit-webrtc APIs."""

    def __init__(self, window_seconds: float = 3.0) -> None:
        self.buffer = QueuedMicrophoneBuffer(window_seconds=window_seconds)
        self.audio_queue = self.buffer.audio_queue

    def recv(self, frame: Any) -> Any:
        self.buffer.add_frame(frame)
        return frame

    def stats(self) -> dict[str, int]:
        return self.buffer.stats()


def make_queued_audio_callback(
    buffer: QueuedMicrophoneBuffer,
) -> Callable[[list[Any]], Any]:
    """Return a queued callback that avoids dropping audio frames in WebRTC."""

    async def queued_audio_callback(frames: list[Any]) -> list[Any]:
        for frame in frames:
            buffer.add_frame(frame)
        return frames

    return queued_audio_callback


class TranscriptionWorker:
    """Background worker that drains mic audio and emits transcript text."""

    def __init__(self, audio_source: QueuedMicrophoneBuffer | MicrophoneAudioProcessor, model_name: str) -> None:
        self.audio_source = audio_source
        self.model_name = model_name
        self.text_queue: queue.Queue[str] = queue.Queue()
        self.error_queue: queue.Queue[str] = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.windows_transcribed = 0
        self.last_text = ""

    @property
    def is_alive(self) -> bool:
        return self.thread.is_alive()

    def start(self) -> "TranscriptionWorker":
        if not self.thread.is_alive():
            self.thread.start()
        return self

    def stop(self) -> None:
        self.stop_event.set()

    def drain_text(self) -> list[str]:
        items: list[str] = []
        while True:
            try:
                items.append(self.text_queue.get_nowait())
            except queue.Empty:
                return items

    def drain_errors(self) -> list[str]:
        items: list[str] = []
        while True:
            try:
                items.append(self.error_queue.get_nowait())
            except queue.Empty:
                return items

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                window = self.audio_source.audio_queue.get(timeout=0.25)
            except queue.Empty:
                continue

            try:
                text = transcribe_chunk(
                    window.samples,
                    sample_rate=window.sample_rate,
                    model_name=self.model_name,
                )
            except STTEngineUnavailable as exc:
                self.error_queue.put(str(exc))
                self.stop_event.set()
            except Exception as exc:  # pragma: no cover - runtime dependent
                self.error_queue.put(f"STT transcription failed: {exc}")
            else:
                self.windows_transcribed += 1
                if text:
                    self.last_text = text
                    self.text_queue.put(text)

    def stats(self) -> dict[str, object]:
        source_stats = (
            self.audio_source.stats()
            if hasattr(self.audio_source, "stats")
            else {}
        )
        return {
            **source_stats,
            "windows_transcribed": self.windows_transcribed,
            "last_text": self.last_text,
            "worker_alive": self.is_alive,
        }


def start_transcription_worker(
    processor: QueuedMicrophoneBuffer | MicrophoneAudioProcessor,
    model_name: str,
) -> TranscriptionWorker:
    return TranscriptionWorker(audio_source=processor, model_name=model_name).start()


def drain_transcripts_to_caption_buffer(
    worker: TranscriptionWorker,
    state: dict[str, object],
    *,
    keep_history: bool,
    max_words: int,
) -> list[str]:
    """Move completed STT text from the worker into the shared caption buffer."""

    transcripts = worker.drain_text()
    for transcript in transcripts:
        append_caption(
            state,
            transcript,
            keep_history=keep_history,
            max_words=max_words,
        )
    return transcripts
