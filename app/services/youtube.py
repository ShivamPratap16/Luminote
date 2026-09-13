"""YouTube URL validation, normalization, and metadata extraction."""
import re
import structlog
from typing import Optional
from dataclasses import dataclass

logger = structlog.get_logger(__name__)

# Supported YouTube URL patterns
_YOUTUBE_PATTERNS = [
    re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([0-9A-Za-z_-]{11})"),
    re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/embed/([0-9A-Za-z_-]{11})"),
    re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/v/([0-9A-Za-z_-]{11})"),
    re.compile(r"(?:https?://)?youtu\.be/([0-9A-Za-z_-]{11})"),
    re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/shorts/([0-9A-Za-z_-]{11})"),
]


@dataclass
class YouTubeMetadata:
    video_id: str
    title: str
    channel_name: Optional[str]
    duration_seconds: Optional[int]
    thumbnail_url: Optional[str]
    description: Optional[str]
    chapters: list  # list of dicts with title, start_seconds, end_seconds


class YouTubeValidationError(Exception):
    """Raised when a YouTube URL is invalid or unsupported."""
    pass


class YouTubeSourceError(Exception):
    """Raised when metadata cannot be fetched (video unavailable, private, etc.)."""
    pass


class YouTubeService:
    """Handles YouTube URL validation, normalization, and metadata extraction."""

    @staticmethod
    def extract_video_id(url: str) -> str:
        """Extract and return the 11-character video ID from a YouTube URL.

        Raises YouTubeValidationError if the URL is not a recognized format.
        """
        for pattern in _YOUTUBE_PATTERNS:
            match = pattern.search(url)
            if match:
                return match.group(1)
        raise YouTubeValidationError(f"Not a supported YouTube URL: {url}")

    @staticmethod
    def normalize_url(video_id: str) -> str:
        """Return the canonical URL form for a given video ID."""
        return f"https://www.youtube.com/watch?v={video_id}"

    @staticmethod
    def fetch_metadata(video_id: str) -> YouTubeMetadata:
        """Fetch video metadata using yt-dlp without downloading media.

        Raises YouTubeSourceError if the video is unavailable.
        """
        import yt_dlp

        url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": False,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as e:
            logger.error("yt-dlp metadata extraction failed", video_id=video_id, error=str(e))
            raise YouTubeSourceError(f"Could not access video {video_id}: {e}")

        # Extract chapters if present
        raw_chapters = info.get("chapters") or []
        chapters = []
        for ch in raw_chapters:
            chapters.append({
                "title": ch.get("title", ""),
                "start_seconds": ch.get("start_time", 0),
                "end_seconds": ch.get("end_time", 0),
            })

        return YouTubeMetadata(
            video_id=video_id,
            title=info.get("title", "Untitled"),
            channel_name=info.get("channel") or info.get("uploader"),
            duration_seconds=info.get("duration"),
            thumbnail_url=info.get("thumbnail"),
            description=info.get("description"),
            chapters=chapters,
        )

    @staticmethod
    def fetch_captions(video_id: str) -> Optional[list[dict]]:
        """Fetch existing captions using youtube-transcript-api.
        
        Returns a normalized list of transcript segments if valid captions are found.
        Returns None if unavailable, invalid, or empty.
        
        Selection preference:
        1. Manual/original English captions
        2. Manual/original other language captions
        3. Auto-generated English captions
        4. Auto-generated other language captions
        """
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled
            
            ytt_api = YouTubeTranscriptApi()
            transcript_list = ytt_api.list(video_id)
            
            # 1. Prefer manual/created transcripts
            selected_transcript = None
            try:
                # Try manual english
                selected_transcript = transcript_list.find_manually_created_transcript(['en'])
            except NoTranscriptFound:
                try:
                    # Fallback to any manual
                    manual_transcripts = transcript_list.find_manually_created_transcript(
                        list(transcript_list._manually_created_transcripts.keys())
                    )
                    selected_transcript = manual_transcripts
                except NoTranscriptFound:
                    # 2. Fallback to generated transcripts
                    try:
                        # Try auto english
                        selected_transcript = transcript_list.find_generated_transcript(['en'])
                    except NoTranscriptFound:
                        try:
                            # Fallback to any auto
                            auto_transcripts = transcript_list.find_generated_transcript(
                                list(transcript_list._generated_transcripts.keys())
                            )
                            selected_transcript = auto_transcripts
                        except NoTranscriptFound:
                            return None
            
            if not selected_transcript:
                return None
                
            raw_captions = list(selected_transcript.fetch())
            
            # Validate and Normalize
            if not raw_captions or not isinstance(raw_captions, (list, object)):
                logger.warning("Fetched captions are empty or invalid", video_id=video_id)
                return None
                
            normalized = []
            for item in raw_captions:
                text = item.get("text", "").strip()
                if not text:
                    continue
                    
                start = float(item.get("start", 0.0))
                duration = float(item.get("duration", 0.0))
                end = start + duration
                
                normalized.append({
                    "start_seconds": start,
                    "end_seconds": end,
                    "text": text,
                })
                
            if not normalized:
                logger.warning("Captions were empty after normalization", video_id=video_id)
                return None
                
            logger.info(
                "Successfully fetched YouTube captions", 
                video_id=video_id, 
                segments=len(normalized),
                is_generated=selected_transcript.is_generated
            )
            return normalized
            
        except Exception as e:
            logger.info("Caption extraction unavailable or failed", video_id=video_id, error=str(e))
            return None
