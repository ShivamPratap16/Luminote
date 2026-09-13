import os
import json
import uuid
import structlog
import yt_dlp
from app.core.config import settings

logger = structlog.get_logger(__name__)

class YouTubeAcquisitionBlocked(Exception):
    """Raised when YouTube blocks automated access (e.g. 'Sign in to confirm you're not a bot')."""
    pass

class YouTubeAcquisitionService:
    @staticmethod
    def _is_cache_valid(cache_path: str) -> bool:
        return os.path.exists(cache_path) and os.path.getsize(cache_path) > 0

    @staticmethod
    def get_video_stream(video_id: str) -> str:
        """Downloads video stream and returns local file path (using cache if enabled)."""
        cache_dir = getattr(settings, 'YOUTUBE_MEDIA_CACHE_DIR', './data/youtube-cache')
        use_cache = getattr(settings, 'YOUTUBE_MEDIA_CACHE_ENABLED', True)
        
        video_dir = os.path.join(cache_dir, video_id)
        video_path = os.path.join(video_dir, "video.mp4")
        
        if use_cache:
            if YouTubeAcquisitionService._is_cache_valid(video_path):
                logger.info('youtube_acquisition', video_id=video_id, cache_hit=True, cache_path=video_path, status='available', file_size=os.path.getsize(video_path))
                return video_path
            elif os.path.exists(video_path):
                logger.warning("Cache invalid, removing", path=video_path)
                os.remove(video_path)

        os.makedirs(video_dir, exist_ok=True)
        temp_path = os.path.join(getattr(settings, 'VISION_TEMP_DIR', './tmp/vision'), f'{video_id}_{uuid.uuid4().hex[:8]}.mp4')
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)

        url = f'https://www.youtube.com/watch?v={video_id}'
        max_height = getattr(settings, 'VISION_VIDEO_MAX_HEIGHT', 720)
        ydl_opts = {
            'format': f'bestvideo[height<={max_height}][ext=mp4]/bestvideo[height<=480][ext=mp4]/best[height<={max_height}]/best',
            'outtmpl': temp_path,
            'quiet': True,
            'no_warnings': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
        except Exception as e:
            err_msg = str(e).lower()
            if "sign in to confirm you" in err_msg and "not a bot" in err_msg:
                logger.error('youtube_acquisition', video_id=video_id, cache_hit=False, status='blocked', error_type='YOUTUBE_ACQUISITION_BLOCKED')
                raise YouTubeAcquisitionBlocked("We couldn't acquire this YouTube video right now because YouTube temporarily blocked automated access. Please try again later.")
            raise Exception(f'Failed to download video: {str(e)}')

        if use_cache:
            import shutil
            shutil.copy(temp_path, video_path)
            logger.info('youtube_acquisition', video_id=video_id, cache_hit=False, cache_path=video_path, status='available', file_size=os.path.getsize(video_path))
            return video_path
        
        return temp_path


