# DHH Subtitle UI Prototype

Streamlit prototype for a classroom-native subtitle band. It focuses on the UI layer for now: subtitle readability, bottom/top placement, slide overlay preview, and switchable caption input modes.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Modes

- Manual input: type or paste a caption line and immediately preview the subtitle band.
- Simulated stream: paste a transcript and stream it word-by-word to mimic real-time STT output.
- Live mic STT: capture microphone audio with `streamlit-webrtc` and transcribe short local windows with `faster-whisper`.

## Notes

The first live STT run may download the selected `faster-whisper` model. The UI remains usable in Manual and Simulated modes even if microphone access, WebRTC, or the STT model is unavailable.

The fullscreen overlay preview is a browser mock of the eventual HDMI overlay: it renders captions over a slide image so font size, contrast, opacity, and positioning can be tuned before working on the hardware pipeline.
