import os
import uuid
import structlog
import subprocess
from PIL import Image
import imagehash
from app.core.config import settings

logger = structlog.get_logger(__name__)

class FrameSelectionService:
    def __init__(self, temp_dir: str | None = None):
        self.temp_dir = temp_dir or settings.MEDIA_TEMP_DIR
        os.makedirs(self.temp_dir, exist_ok=True)

    def select_frames(self, video_id: str):
        # 1. Acquire video stream (worstvideo / max height 720p)
        logger.info('Acquiring video stream for frames', video_id=video_id)
        
        # yt-dlp to get direct stream URL for 720p max
        try:
            import yt_dlp
            url = f'https://www.youtube.com/watch?v={video_id}'
            ydl_opts = {
                'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
                'quiet': True,
                'no_warnings': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                stream_url = info.get('url')
                if not stream_url:
                    formats = info.get('formats', [])
                    for f in reversed(formats):
                        if f.get('vcodec') != 'none':
                            stream_url = f.get('url')
                            break
        except Exception as e:
            logger.error('Failed to acquire video stream', video_id=video_id, error=str(e))
            raise

        if not stream_url:
            raise ValueError('Could not find suitable video stream URL')

        # 2. Frame Extraction via FFmpeg (scene detection + sampling)
        out_dir = os.path.join(self.temp_dir, f'{video_id}_frames_{uuid.uuid4().hex[:8]}')
        os.makedirs(out_dir, exist_ok=True)

        logger.info('Extracting frames via ffmpeg', out_dir=out_dir)
        # We sample 1 frame per 2 seconds, and also apply a scene filter to catch important changes
        # But for V1, just sampling at 1fps and scene change is easiest.
        # select='gt(scene,0.3)' filters scene changes.
        # We will output frames with timestamp in filename.
        # Actually ffmpeg select can output scene changes, but getting exact timestamps in filenames is tricky.
        # Let's just use fps=1 to extract 1 frame per second, then deduplicate visually. It's robust.
        
        ffmpeg_cmd = [
            'ffmpeg', '-y', '-i', stream_url,
            '-vf', 'fps=1', # 1 frame per second
            '-vsync', 'vfr',
            '-q:v', '2', # high quality JPEG
            os.path.join(out_dir, 'frame_%05d.jpg')
        ]
        
        try:
            subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
        except subprocess.TimeoutExpired:
            logger.error('ffmpeg frame extraction timed out')
            raise
        except subprocess.CalledProcessError as e:
            logger.error('ffmpeg frame extraction failed', error=str(e))
            raise

        # 3. Deduplication and Selection
        frames = sorted(os.listdir(out_dir))
        selected_events = []
        last_hash = None
        
        for frame_file in frames:
            # frame_00001.jpg -> index 1 -> 1 second (since fps=1)
            idx = int(frame_file.split('_')[1].split('.')[0])
            timestamp = float(idx - 1)
            
            frame_path = os.path.join(out_dir, frame_file)
            
            try:
                img = Image.open(frame_path)
                current_hash = imagehash.phash(img)
            except Exception as e:
                logger.warning('Failed to hash frame', path=frame_path, error=str(e))
                continue
                
            # Compare with last hash
            if last_hash is None or current_hash - last_hash > 10: # threshold for difference
                selected_events.append({
                    'timestamp': timestamp,
                    'frame_path': frame_path,
                    'frame_hash': str(current_hash)
                })
                last_hash = current_hash
            else:
                # Duplicate, we can remove the file to save space
                os.remove(frame_path)
                
        logger.info('Frame selection complete', video_id=video_id, candidates=len(frames), selected=len(selected_events))
        return selected_events, out_dir
