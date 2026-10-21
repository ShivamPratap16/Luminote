import os
import json
import uuid
import structlog
import yt_dlp
import shutil
from app.core.config import settings
from app.services.temp_lifecycle import TempLifecycleService

logger = structlog.get_logger(__name__)

class YouTubeAcquisitionBlocked(Exception):
    """Raised when YouTube blocks automated access (e.g. 'Sign in to confirm you're not a bot')."""
    pass

class VideoSizeLimitExceeded(Exception):
    """Raised when a video exceeds configured duration or size limits."""
    pass

class YouTubeAcquisitionService:
    @staticmethod
    def _is_cache_valid(cache_path: str) -> bool:
        return os.path.exists(cache_path) and os.path.getsize(cache_path) > 0

    @staticmethod
    def get_video_stream(video_id: str, job_dir: str = None) -> str:
        """Downloads video stream and returns local file path.
        Uses two-phase validation for duration/size limits.
        """
        cache_dir = getattr(settings, 'YOUTUBE_MEDIA_CACHE_DIR', './data/youtube-cache')
        use_cache = getattr(settings, 'YOUTUBE_MEDIA_PERSISTENT_CACHE_ENABLED', False)
        
        video_dir = os.path.join(cache_dir, video_id)
        cached_video_path = os.path.join(video_dir, "video.mp4")
        
        # If cache is enabled and valid, skip download entirely
        if use_cache and YouTubeAcquisitionService._is_cache_valid(cached_video_path):
            logger.info('youtube_acquisition', video_id=video_id, cache_hit=True, cache_path=cached_video_path, status='available', file_size=os.path.getsize(cached_video_path))
            # If we have a job dir, copy it there to keep isolation. Or we can just return cache path.
            # But the requirement implies temp video lifecycle should be managed. Since it's a dev cache, we can just return it.
            # Actually, to be perfectly consistent with job lifecycle, let's copy to job_dir if provided.
            if job_dir:
                job_video_path = os.path.join(job_dir, "video", "video.mp4")
                shutil.copy(cached_video_path, job_video_path)
                return job_video_path
            return cached_video_path

        # Check machine/app storage before even trying to download
        TempLifecycleService.check_machine_disk()
        TempLifecycleService.check_app_storage()

        url = f'https://www.youtube.com/watch?v={video_id}'
        max_height = getattr(settings, 'VISION_VIDEO_MAX_HEIGHT', 720)
        
        ydl_opts_base = {
            'format': f'bestvideo[height<={max_height}][ext=mp4]/bestvideo[height<=480][ext=mp4]/best[height<={max_height}]/best',
            'quiet': True,
            'no_warnings': True,
        }

        # 1. Pre-download checks
        try:
            with yt_dlp.YoutubeDL(ydl_opts_base) as ydl:
                info = ydl.extract_info(url, download=False)
                
                duration = info.get("duration", 0)
                max_duration_min = getattr(settings, 'MAX_VIDEO_DURATION_MINUTES', 240)
                if duration > max_duration_min * 60:
                    raise VideoSizeLimitExceeded(f"Video duration ({duration}s) exceeds limit ({max_duration_min * 60}s)")
                    
                # We could estimate size here if info.get('filesize') is reliable, but it often isn't for DASH formats.
        except Exception as e:
            if isinstance(e, VideoSizeLimitExceeded):
                raise
            err_msg = str(e).lower()
            if "sign in to confirm you" in err_msg and "not a bot" in err_msg:
                logger.error('youtube_acquisition', video_id=video_id, cache_hit=False, status='blocked', error_type='YOUTUBE_ACQUISITION_BLOCKED')
                raise YouTubeAcquisitionBlocked("We couldn't acquire this YouTube video right now because YouTube temporarily blocked automated access.")
            raise Exception(f'Failed to extract video info: {str(e)}')

        # Determine target path
        if job_dir:
            target_path = os.path.join(job_dir, "video", "video.mp4")
        else:
            target_path = os.path.join(TempLifecycleService.get_base_dir(), f'{video_id}_{uuid.uuid4().hex[:8]}.mp4')
            
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        
        ydl_opts = ydl_opts_base.copy()
        ydl_opts['outtmpl'] = target_path

        # 2. Download
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
        except Exception as e:
            err_msg = str(e).lower()
            if "sign in to confirm you" in err_msg and "not a bot" in err_msg:
                logger.error('youtube_acquisition', video_id=video_id, cache_hit=False, status='blocked', error_type='YOUTUBE_ACQUISITION_BLOCKED')
                raise YouTubeAcquisitionBlocked("We couldn't acquire this YouTube video right now because YouTube temporarily blocked automated access.")
            raise Exception(f'Failed to download video: {str(e)}')

        # 3. Post-download checks
        actual_size_bytes = os.path.getsize(target_path)
        actual_size_mb = actual_size_bytes / (1024 * 1024)
        max_size_mb = getattr(settings, 'MAX_VIDEO_SIZE_MB', 2048)
        
        if actual_size_mb > max_size_mb:
            os.remove(target_path)
            raise VideoSizeLimitExceeded(f"Video size ({actual_size_mb:.2f} MB) exceeds limit ({max_size_mb} MB)")

        # Persistent cache (development only)
        if use_cache:
            os.makedirs(video_dir, exist_ok=True)
            shutil.copy(target_path, cached_video_path)
            logger.info('youtube_acquisition', video_id=video_id, cache_hit=False, cache_path=cached_video_path, status='cached_for_dev')

        logger.info('youtube_acquisition', video_id=video_id, cache_hit=False, path=target_path, size_mb=round(actual_size_mb, 1), status='downloaded')
        return target_path
