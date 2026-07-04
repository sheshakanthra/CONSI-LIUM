"""ASR pipeline using faster-whisper.

WHY faster-whisper: CLAUDE.md locks local ASR to faster-whisper (a CTranslate2
Whisper reimplementation) for dev, with a Whisper-API swap-in reserved for prod.
It decodes audio itself (via bundled PyAV), so no system ffmpeg is required.

WHY VAD filtering on: earnings-call audio has silences; voice-activity
filtering keeps Whisper from hallucinating text over dead air and yields
cleaner segment boundaries.

WHY cache the model: loading the CTranslate2 weights is the expensive part.
``@lru_cache`` keeps one model per (name, device, compute_type) alive for the
process so ingesting many files doesn't reload it each time.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import Settings
from ingestion.errors import IngestionError


@dataclass
class SegmentData:
    """One timestamped transcript segment."""

    index: int
    start: float
    end: float
    text: str


@dataclass
class TranscriptData:
    """Full ASR result for one audio file."""

    language: str | None
    duration: float | None
    model_name: str
    segments: list[SegmentData]


@lru_cache(maxsize=4)
def _load_model(model_name: str, device: str, compute_type: str):
    """Load (and cache) a WhisperModel.

    Import is local so the heavy faster-whisper/ctranslate2 import cost is only
    paid when ASR actually runs, not on every ``import ingestion``.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - dependency wiring
        raise IngestionError(
            "faster-whisper is not installed; cannot run the ASR pipeline"
        ) from exc

    try:
        return WhisperModel(model_name, device=device, compute_type=compute_type)
    except Exception as exc:  # noqa: BLE001 — surface model-load failures loudly.
        raise IngestionError(
            f"Failed to load Whisper model '{model_name}' "
            f"(device={device}, compute_type={compute_type}): {exc}"
        ) from exc


def transcribe(path: str | Path, settings: Settings) -> TranscriptData:
    """Transcribe an audio file into timestamped segments.

    Raises:
        IngestionError: if the file is missing or transcription fails.
    """
    audio_path = Path(path)
    if not audio_path.is_file():
        raise IngestionError(f"Audio file not found: {audio_path}")

    model = _load_model(
        settings.whisper_model, settings.whisper_device, settings.whisper_compute_type
    )

    try:
        # `segments` is a lazy generator; iterating it is what actually runs
        # inference. We materialise it here so any decode error surfaces now,
        # inside this try/except, rather than later at the DB-write site.
        segment_iter, info = model.transcribe(
            str(audio_path),
            language=settings.whisper_language,
            vad_filter=True,
        )
        segments = [
            SegmentData(
                index=i,
                start=float(seg.start),
                end=float(seg.end),
                text=(seg.text or "").strip(),
            )
            for i, seg in enumerate(segment_iter)
        ]
    except Exception as exc:  # noqa: BLE001 — wrap with file context.
        raise IngestionError(f"Failed to transcribe {audio_path}: {exc}") from exc

    return TranscriptData(
        language=getattr(info, "language", None),
        duration=getattr(info, "duration", None),
        model_name=settings.whisper_model,
        segments=segments,
    )
