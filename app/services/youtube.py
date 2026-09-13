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
    re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/live/([0-9A-Za-z_-]{11})"),
]

class YouTubeValidationError(Exception):
    pass

class YouTubeSourceError(Exception):
    pass

@dataclass
class YouTubeMetadata:
    video_id: str
    title: str
    channel_name: str
    duration_seconds: int
    thumbnail_url: Optional[str] = None
    description: Optional[str] = None
    chapters: list = None

class YouTubeService:
    @staticmethod
    def extract_video_id(url: str) -> str:
        for pattern in _YOUTUBE_PATTERNS:
            match = pattern.search(url)
            if match:
                return match.group(1)
        raise YouTubeValidationError(f"Not a supported YouTube URL: {url}")

    @staticmethod
    def normalize_url(video_id: str) -> str:
        return f"https://www.youtube.com/watch?v={video_id}"

    @staticmethod
    def fetch_metadata(video_id: str) -> YouTubeMetadata:
        import yt_dlp
        from app.services.youtube_acquisition import YouTubeAcquisitionBlocked
        
        url = YouTubeService.normalize_url(video_id)
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
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
        except Exception as e:
            err_msg = str(e).lower()
            if "sign in to confirm you" in err_msg and "not a bot" in err_msg:
                logger.error('youtube_acquisition', video_id=video_id, cache_hit=False, status='blocked', error_type='YOUTUBE_ACQUISITION_BLOCKED')
                raise YouTubeAcquisitionBlocked("YouTube temporarily blocked automated access.")
                
            logger.error("Failed to fetch YouTube metadata", video_id=video_id, error=str(e))
            raise YouTubeSourceError(f"Could not fetch metadata for {video_id}: {e}")

    @staticmethod
    def fetch_captions(video_id: str) -> Optional[list[dict]]:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled
            
            ytt_api = YouTubeTranscriptApi()
            transcript_list = ytt_api.list(video_id)
            
            selected_transcript = None
            try:
                selected_transcript = transcript_list.find_manually_created_transcript(['en'])
            except NoTranscriptFound:
                try:
                    manual_transcripts = transcript_list.find_manually_created_transcript(
                        list(transcript_list._manually_created_transcripts.keys())
                    )
                    selected_transcript = manual_transcripts
                except NoTranscriptFound:
                    try:
                        selected_transcript = transcript_list.find_generated_transcript(['en'])
                    except NoTranscriptFound:
                        try:
                            auto_transcripts = transcript_list.find_generated_transcript(
                                list(transcript_list._generated_transcripts.keys())
                            )
                            selected_transcript = auto_transcripts
                        except NoTranscriptFound:
                            return None
            
            if not selected_transcript:
                return None
                
            raw_captions = list(selected_transcript.fetch())
            
            if not raw_captions or not isinstance(raw_captions, (list, object)):
                return None
                
            normalized = []
            for item in raw_captions:
                if hasattr(item, 'text'):
                    text = getattr(item, 'text', '').strip()
                    start = float(getattr(item, 'start', 0.0))
                    duration = float(getattr(item, 'duration', 0.0))
                else:
                    text = item.get("text", "").strip()
                    start = float(item.get("start", 0.0))
                    duration = float(item.get("duration", 0.0))

                if not text:
                    continue
                    
                end = start + duration
                
                normalized.append({
                    "start_seconds": start,
                    "end_seconds": end,
                    "text": text,
                })

            if not normalized:
                return None
                
            return normalized
            
        except Exception as e:
            logger.info("Caption extraction unavailable or failed", video_id=video_id, error=str(e))
            return None