"""Gemini speech helpers for the Gradio workbench.

STT uses the configured chat model with an audio part (google-genai).
TTS is attempted on a Gemini TTS preview model and skipped if unavailable.
No OpenAI Whisper.
"""

from __future__ import annotations

import io
import tempfile
import wave
from pathlib import Path
from typing import Any

from navaid.config import NAVAID_MODEL
from navaid.gemini_client import gemini_configured, make_genai_client

STT_FALLBACK = (
    "Microphone transcription needs GEMINI_API_KEY or gcloud ADC "
    "(gcloud auth login --update-adc). Type the question in the box instead."
)
TTS_MODELS = (
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts",
)
CUSTOM_VOCAB = (
    "LAX",
    "SNA",
    "SFO",
    "ANC",
    "TEOI",
    "enplanements",
    "New England",
    "Santa Ana",
    "Anchorage",
)


def gemini_voice_ready() -> bool:
    return gemini_configured()


def transcribe(audio: Any) -> tuple[str, str]:
    """Return (transcript, status). Empty transcript means use the text box."""

    if audio is None or audio == "":
        return "", "No microphone audio. Type the question, or record and transcribe."
    if not gemini_configured():
        return "", STT_FALLBACK
    try:
        blob, mime = _audio_to_bytes(audio)
    except Exception as exc:
        return "", f"Could not read microphone audio ({exc}). Type the question instead."
    if not blob:
        return "", "Empty recording. Type the question instead."
    try:
        text = _gemini_stt(blob, mime)
    except Exception as exc:
        return "", f"Gemini STT failed ({exc}). Type the question instead — Whisper is not used."
    text = (text or "").strip()
    if not text:
        return "", "Gemini returned an empty transcript. Type the question instead."
    return text, "Transcribed with Gemini (chat model audio). Edit before asking if needed."


def synthesize(text: str) -> tuple[str | None, str]:
    """Return (wav path or None, status)."""

    spoken = (text or "").strip()
    if not spoken:
        return None, "Nothing to speak."
    if not gemini_configured():
        return None, "TTS needs GEMINI_API_KEY or gcloud ADC. Read the text answer instead."
    clipped = spoken if len(spoken) <= 1600 else spoken[:1600] + "…"
    last_error = "no TTS model tried"
    for model in TTS_MODELS:
        try:
            pcm, rate = _gemini_tts(clipped, model)
            path = _write_wav(pcm, rate)
            return path, f"Spoken with Gemini TTS ({model})."
        except Exception as exc:
            last_error = str(exc)
            continue
    return None, f"Gemini TTS unavailable ({last_error}). Read the text answer instead."


def synthesize_wav_bytes(text: str) -> tuple[bytes | None, str]:
    """WAV bytes for the site player. Cleans up the temp file from ``synthesize``."""

    path, note = synthesize(text)
    if not path:
        return None, note
    file_path = Path(path)
    try:
        return file_path.read_bytes(), note
    finally:
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass


def _audio_to_bytes(audio: Any) -> tuple[bytes, str]:
    if isinstance(audio, dict):
        path = audio.get("path") or audio.get("name")
        if path:
            return _audio_to_bytes(path)
        data = audio.get("data")
        if data:
            return bytes(data), str(audio.get("mime_type") or "audio/wav")
    if isinstance(audio, (str, Path)):
        path = Path(audio)
        mime = _mime_for(path.suffix)
        return path.read_bytes(), mime
    if isinstance(audio, tuple) and len(audio) == 2:
        rate, array = audio
        return _numpy_wav_bytes(int(rate), array), "audio/wav"
    raise TypeError(f"unsupported audio value: {type(audio)!r}")


def _mime_for(suffix: str) -> str:
    mapping = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".webm": "audio/webm",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
        ".flac": "audio/flac",
        ".aac": "audio/aac",
    }
    return mapping.get(suffix.lower(), "audio/wav")


def _numpy_wav_bytes(rate: int, array: Any) -> bytes:
    import numpy as np

    data = np.asarray(array)
    if data.ndim > 1:
        data = data[:, 0]
    if data.dtype != np.int16:
        if np.issubdtype(data.dtype, np.floating):
            peak = float(np.max(np.abs(data))) or 1.0
            data = (data / peak * 32767.0).astype(np.int16)
        else:
            data = data.astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(rate) if rate else 16000)
        wf.writeframes(data.tobytes())
    return buf.getvalue()


def _write_wav(pcm: bytes, rate: int) -> str:
    if pcm[:4] == b"RIFF":
        handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        handle.write(pcm)
        handle.close()
        return handle.name
    handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(handle, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(rate) or 24000)
        wf.writeframes(pcm)
    return handle.name


def _client():
    return make_genai_client()


def _gemini_stt(blob: bytes, mime: str) -> str:
    from google.genai import types

    vocab = ", ".join(CUSTOM_VOCAB)
    prompt = (
        "Transcribe this analyst question exactly. Return only the transcript, "
        "no quotes or commentary. Aviation terms you may hear: "
        f"{vocab}."
    )
    response = _client().models.generate_content(
        model=NAVAID_MODEL,
        contents=[
            types.Part.from_bytes(data=blob, mime_type=mime),
            prompt,
        ],
        config=types.GenerateContentConfig(temperature=0.0),
    )
    text = getattr(response, "text", None)
    if text:
        return str(text).strip()
    parts: list[str] = []
    for cand in getattr(response, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            piece = getattr(part, "text", None)
            if piece:
                parts.append(str(piece))
    return "".join(parts).strip()


def _gemini_tts(text: str, model: str) -> tuple[bytes, int]:
    from google.genai import types

    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
            )
        ),
    )
    response = _client().models.generate_content(
        model=model,
        contents=text,
        config=config,
    )
    for cand in getattr(response, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            if inline is None:
                continue
            data = getattr(inline, "data", None)
            if not data:
                continue
            mime = str(getattr(inline, "mime_type", "") or "")
            rate = 24000
            if "rate=" in mime:
                try:
                    rate = int(mime.split("rate=", 1)[1].split(";")[0])
                except ValueError:
                    rate = 24000
            raw = data if isinstance(data, (bytes, bytearray)) else bytes(data)
            return bytes(raw), rate
    raise RuntimeError("TTS response had no audio part")


__all__ = [
    "STT_FALLBACK",
    "gemini_voice_ready",
    "synthesize",
    "synthesize_wav_bytes",
    "transcribe",
]
