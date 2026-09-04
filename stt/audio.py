"""
Small audio helpers -- reading an upload's bytes + best-effort duration without
pulling in a heavy dependency or shelling to ffmpeg.
"""

from __future__ import annotations

import contextlib
import io
import wave
from pathlib import Path

_MIME_BY_EXT = {
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
    ".flac": "audio/flac", ".ogg": "audio/ogg", ".aac": "audio/aac",
    ".webm": "audio/webm",
}


def read_upload(uploaded_file) -> tuple[bytes, str, str]:
    """(bytes, mime_type, filename) from a Streamlit UploadedFile / audio_input."""
    data = uploaded_file.getvalue()
    name = getattr(uploaded_file, "name", None) or "recording.wav"
    mime = getattr(uploaded_file, "type", None) or _MIME_BY_EXT.get(
        Path(name).suffix.lower(), "audio/wav"
    )
    return data, mime, name


def duration_seconds(data: bytes, filename: str = "") -> float | None:
    """Best-effort duration. Reads WAV headers from the bytes; otherwise None
    (the quality checks degrade gracefully without a duration)."""
    is_wav = filename.lower().endswith(".wav") or data[:4] == b"RIFF"
    if is_wav:
        with contextlib.suppress(Exception), wave.open(io.BytesIO(data), "rb") as w:
            frames, rate = w.getnframes(), w.getframerate()
            if rate:
                return frames / float(rate)
    try:  # optional, not in requirements
        from mutagen import File as MutagenFile

        mf = MutagenFile(io.BytesIO(data))
        if mf is not None and mf.info is not None:
            return float(mf.info.length)
    except Exception:
        pass
    return None
