"""Transcription service with provider abstraction around faster-whisper."""
import structlog
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List
from app.core.config import settings

logger = structlog.get_logger(__name__)


@dataclass
class TranscriptSegment:
    """A single timestamped transcript segment."""
    segment_index: int
    start_seconds: float
    end_seconds: float
    text: str


class TranscriptionError(Exception):
    """Raised when transcription fails."""
    pass


class TranscriptionProvider(ABC):
    """Abstract interface for transcription providers.

    Future providers (cloud APIs, etc.) implement this interface.
    """

    @abstractmethod
    def transcribe(self, audio_path: str) -> List[TranscriptSegment]:
        """Transcribe an audio file and return ordered segments."""
        ...


class WhisperTranscriptionProvider(TranscriptionProvider):
    """Transcription using faster-whisper (local inference)."""

    def __init__(
        self,
        model_size: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
    ):
        self.model_size = model_size or settings.WHISPER_MODEL_SIZE
        self.device = device or settings.WHISPER_DEVICE
        self.compute_type = compute_type or settings.WHISPER_COMPUTE_TYPE
        self._model = None

    def _get_model(self):
        """Lazy-load the Whisper model to avoid loading at import time."""
        if self._model is None:
            from faster_whisper import WhisperModel
            logger.info(
                "Loading Whisper model",
                model_size=self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model

    def transcribe(self, audio_path: str) -> List[TranscriptSegment]:
        """Transcribe audio file using faster-whisper.

        Returns a list of TranscriptSegment with stable ordering.
        Raises TranscriptionError on failure.
        """
        logger.info("Starting transcription", audio_path=audio_path)
        try:
            model = self._get_model()
            segments_iter, info = model.transcribe(
                audio_path,
                beam_size=5,
                vad_filter=True,
            )

            segments: List[TranscriptSegment] = []
            for idx, seg in enumerate(segments_iter):
                segments.append(TranscriptSegment(
                    segment_index=idx,
                    start_seconds=round(seg.start, 2),
                    end_seconds=round(seg.end, 2),
                    text=seg.text.strip(),
                ))

            logger.info(
                "Transcription complete",
                audio_path=audio_path,
                segment_count=len(segments),
                detected_language=info.language,
                language_probability=round(info.language_probability, 2),
            )
            return segments

        except Exception as e:
            logger.error("Transcription failed", audio_path=audio_path, error=str(e))
            raise TranscriptionError(f"Transcription failed: {e}")


class TranscriptionService:
    """Application-level transcription service that delegates to a provider."""

    def __init__(self, provider: TranscriptionProvider | None = None):
        self.provider = provider or WhisperTranscriptionProvider()

    def transcribe(self, audio_path: str) -> List[TranscriptSegment]:
        """Transcribe audio and return segments."""
        return self.provider.transcribe(audio_path)
