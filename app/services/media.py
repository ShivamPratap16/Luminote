"""Media download and audio preparation using yt-dlp and FFmpeg."""
import os
import uuid
import structlog
from dataclasses import dataclass
from app.core.config import settings

logger = structlog.get_logger(__name__)


@dataclass
class PreparedAudio:
    """Result of audio preparation: a local file path to a normalized audio file."""
    file_path: str
    format: str  # e.g. "wav", "mp3"
    duration_seconds: float


class MediaPreparationError(Exception):
    """Raised when media download or audio conversion fails."""
    pass


class MediaService:
    """Downloads video audio and normalizes it for transcription."""

    def __init__(self, temp_dir: str | None = None):
        self.temp_dir = temp_dir or settings.MEDIA_TEMP_DIR
        os.makedirs(self.temp_dir, exist_ok=True)

    def prepare_audio(self, video_id: str) -> PreparedAudio:
        """Download audio from YouTube and convert to 16kHz mono WAV for Whisper.

        Returns a PreparedAudio with the local file path.
        Raises MediaPreparationError on failure.
        """
        import yt_dlp

        output_filename = f"{video_id}_{uuid.uuid4().hex[:8]}.wav"
        output_path = os.path.join(self.temp_dir, output_filename)

        url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "outtmpl": os.path.join(self.temp_dir, f"{video_id}_raw.%(ext)s"),
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
            }],
            "postprocessor_args": [
                "-ar", "16000",    # 16kHz sample rate for Whisper
                "-ac", "1",        # mono channel
            ],
        }

        logger.info("Downloading and converting audio", video_id=video_id)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                duration = info.get("duration", 0)
        except Exception as e:
            logger.error("Media preparation failed", video_id=video_id, error=str(e))
            raise MediaPreparationError(f"Failed to prepare audio for {video_id}: {e}")

        # yt-dlp with FFmpeg postprocessor outputs as .wav
        raw_wav = os.path.join(self.temp_dir, f"{video_id}_raw.wav")
        if os.path.exists(raw_wav):
            # Rename to our controlled filename
            os.rename(raw_wav, output_path)
        else:
            # Search for any generated file with this prefix
            for f in os.listdir(self.temp_dir):
                if f.startswith(f"{video_id}_raw") and f.endswith(".wav"):
                    os.rename(os.path.join(self.temp_dir, f), output_path)
                    break
            else:
                raise MediaPreparationError(
                    f"Audio conversion produced no output file for {video_id}"
                )

        logger.info("Audio prepared", video_id=video_id, path=output_path, duration=duration)
        return PreparedAudio(
            file_path=output_path,
            format="wav",
            duration_seconds=float(duration or 0),
        )

    @staticmethod
    def cleanup_file(file_path: str) -> None:
        """Remove a temporary audio file after processing."""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info("Cleaned up temp file", path=file_path)
        except OSError as e:
            logger.warning("Failed to clean up temp file", path=file_path, error=str(e))
