import os
import uuid
import structlog
import subprocess
import time
from PIL import Image
import imagehash
from app.core.config import settings

logger = structlog.get_logger(__name__)

class FrameSelectionService:
    def __init__(self, temp_dir: str | None = None):
        self.temp_dir = getattr(settings, 'VISION_TEMP_DIR', './tmp/vision')
        os.makedirs(self.temp_dir, exist_ok=True)
        self.max_height = getattr(settings, 'VISION_VIDEO_MAX_HEIGHT', 720)
        self.interval = getattr(settings, 'VISION_FRAME_INTERVAL_SECONDS', 10)

    def select_frames(self, video_id: str):
        import yt_dlp
        url = f'https://www.youtube.com/watch?v={video_id}'
        local_video_path = os.path.join(self.temp_dir, f'{video_id}_{uuid.uuid4().hex[:8]}.mp4')
        
        ydl_opts = {
            'format': f'bestvideo[height<={self.max_height}][ext=mp4]/bestvideo[height<=480][ext=mp4]/best[height<={self.max_height}]/best',
            'outtmpl': local_video_path,
            'quiet': True,
            'no_warnings': True,
        }

        logger.info('video download started', video_id=video_id)
        
        # Bounded exponential backoff for download
        max_retries = 3
        download_success = False
        for attempt in range(max_retries):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    actual_height = info.get('height')
                    logger.info('download completed', video_id=video_id, downloaded_resolution=actual_height, local_file_path=local_video_path)
                    download_success = True
                    break
            except Exception as e:
                logger.warning('yt-dlp download failed', attempt=attempt+1, error=str(e))
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise Exception(f'Failed to download video after {max_retries} attempts: {str(e)}')

        out_dir = os.path.join(self.temp_dir, f'{video_id}_frames_{uuid.uuid4().hex[:8]}')
        os.makedirs(out_dir, exist_ok=True)

        try:
            logger.info('frame extraction started', out_dir=out_dir)
            fps = 1.0 / self.interval
            ffmpeg_cmd = [
                'ffmpeg', '-y', '-i', local_video_path.replace('\\', '/'),
                '-vf', f'fps={fps}', 
                '-fps_mode', 'vfr',
                '-q:v', '2',
                os.path.join(out_dir, 'frame_%05d.jpg').replace('\\', '/')
            ]
            
            try:
                subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
            except subprocess.TimeoutExpired:
                logger.error('ffmpeg frame extraction timed out')
                raise
            except subprocess.CalledProcessError as e:
                logger.error('ffmpeg frame extraction failed', error=str(e))
                raise

            # Deduplication and Selection
            frames = sorted(os.listdir(out_dir))
            logger.info('candidate frame count', candidates=len(frames))
            selected_events = []
            last_hash = None
            
            for frame_file in frames:
                idx = int(frame_file.split('_')[1].split('.')[0])
                timestamp = float(idx - 1) * self.interval
                
                frame_path = os.path.join(out_dir, frame_file)
                try:
                    img = Image.open(frame_path)
                    current_hash = imagehash.phash(img)
                except Exception as e:
                    logger.warning('Failed to hash frame', path=frame_path, error=str(e))
                    continue
                    
                if last_hash is None or current_hash - last_hash > 10:
                    selected_events.append({
                        'timestamp': timestamp,
                        'frame_path': frame_path,
                        'frame_hash': str(current_hash)
                    })
                    last_hash = current_hash
                else:
                    os.remove(frame_path)
                    
            logger.info('deduplicated frame count', selected=len(selected_events))
            return selected_events, out_dir

        finally:
            # Clean up the local video file
            if os.path.exists(local_video_path):
                try:
                    os.remove(local_video_path)
                    logger.info('cleanup completed', file=local_video_path)
                except Exception as e:
                    logger.warning('Failed to cleanup local video', file=local_video_path, error=str(e))


