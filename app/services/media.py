import os
import uuid
import structlog
import subprocess
from dataclasses import dataclass
from app.core.config import settings

logger = structlog.get_logger(__name__)

@dataclass
class PreparedAudio:
    file_path: str
    format: str
    duration_seconds: float

class MediaPreparationError(Exception):
    pass

class MediaService:
    def __init__(self, temp_dir: str | None = None):
        pass # Not heavily used now that we have temp lifecycle

    def prepare_audio(self, video_id: str, job_dir: str = None) -> PreparedAudio:
        import yt_dlp
        from app.services.youtube_acquisition import YouTubeAcquisitionBlocked, YouTubeAcquisitionService
        from app.services.temp_lifecycle import TempLifecycleService
        
        if job_dir:
            output_path = os.path.join(job_dir, "audio", "audio.wav")
            temp_work_dir = os.path.join(job_dir, "audio")
        else:
            temp_work_dir = getattr(settings, 'MEDIA_TEMP_DIR', './tmp/media')
            os.makedirs(temp_work_dir, exist_ok=True)
            output_path = os.path.join(temp_work_dir, f"{video_id}_{uuid.uuid4().hex[:8]}.wav")

        cache_dir = getattr(settings, 'YOUTUBE_MEDIA_CACHE_DIR', './data/youtube-cache')
        cached_video = os.path.join(cache_dir, video_id, "video.mp4")

        duration = 0
        
        # We can extract directly from the downloaded MP4 in the job_dir instead of downloading audio again,
        # but yt-dlp extracting bestaudio is usually better quality. 
        # For simplicity and preserving existing behavior, we will download the audio.
        # However, if dev cache is enabled and valid, we'll try to extract from that first.
        use_cache = getattr(settings, 'YOUTUBE_MEDIA_PERSISTENT_CACHE_ENABLED', False)
        
        if use_cache and YouTubeAcquisitionService._is_cache_valid(cached_video):
            logger.info("Extracting audio from cached video", video_id=video_id, cache_path=cached_video)
            ffmpeg_cmd = [
                'ffmpeg', '-y', '-i', cached_video,
                '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1',
                output_path
            ]
            try:
                subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                # We could run ffprobe to get duration, but for now we can just return 0 or rely on Whisper returning segments
            except Exception as e:
                logger.error("Failed to extract audio from cache", error=str(e))
                raise MediaPreparationError(f"Failed to extract audio from cache: {e}")
        else:
            url = f"https://www.youtube.com/watch?v={video_id}"
            
            TempLifecycleService.check_machine_disk()
            TempLifecycleService.check_app_storage()
            
            ydl_opts = {
                "format": "bestaudio/best",
                "quiet": True,
                "no_warnings": True,
                "outtmpl": os.path.join(temp_work_dir, f"{video_id}_raw.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "wav",
                }],
                "postprocessor_args": [
                    "-ar", "16000",
                    "-ac", "1",
                ],
            }

            logger.info("Downloading and converting audio", video_id=video_id)
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    duration = info.get("duration", 0)
            except Exception as e:
                err_msg = str(e).lower()
                if "sign in to confirm you" in err_msg and "not a bot" in err_msg:
                    logger.error('youtube_acquisition', video_id=video_id, cache_hit=False, status='blocked', error_type='YOUTUBE_ACQUISITION_BLOCKED')
                    raise YouTubeAcquisitionBlocked("YouTube temporarily blocked automated access.")
                logger.error("Media preparation failed", video_id=video_id, error=str(e))
                raise MediaPreparationError(f"Failed to prepare audio for {video_id}: {e}")

            raw_wav = os.path.join(temp_work_dir, f"{video_id}_raw.wav")
            if os.path.exists(raw_wav):
                os.rename(raw_wav, output_path)
            else:
                for f in os.listdir(temp_work_dir):
                    if f.startswith(f"{video_id}_raw") and f.endswith(".wav"):
                        os.rename(os.path.join(temp_work_dir, f), output_path)
                        break
                else:
                    raise MediaPreparationError(f"Audio conversion produced no output file for {video_id}")

        logger.info("Audio prepared", video_id=video_id, path=output_path, duration=duration)
        return PreparedAudio(
            file_path=output_path,
            format="wav",
            duration_seconds=float(duration or 0),
        )

    @staticmethod
    def cleanup_file(file_path: str) -> None:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info("Cleaned up temp file", path=file_path)
        except OSError as e:
            logger.warning("Failed to clean up temp file", path=file_path, error=str(e))
