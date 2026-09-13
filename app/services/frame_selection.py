import os
import uuid
import structlog
import subprocess
import time
from typing import List, Dict, Any, Optional
from PIL import Image
import imagehash
from app.core.config import settings

logger = structlog.get_logger(__name__)

VISUAL_KEYWORDS = [
    "diagram", "architecture", "graph", "chart", "table", "formula", 
    "equation", "algorithm", "process", "workflow", "flow", "comparison", 
    "example", "code", "figure", "image", "screenshot", "slide", 
    "as you can see", "look at", "this diagram", "this figure", 
    "on the screen", "here we have", "let's look at", "notice that"
]

class FrameSelectionService:
    def __init__(self, temp_dir: str | None = None):
        self.temp_dir = getattr(settings, 'VISION_TEMP_DIR', './tmp/vision')
        os.makedirs(self.temp_dir, exist_ok=True)
        self.max_height = getattr(settings, 'VISION_VIDEO_MAX_HEIGHT', 720)
        self.interval = getattr(settings, 'VISION_FRAME_INTERVAL_SECONDS', 10)
        self.max_frames = getattr(settings, 'VISION_MAX_ANALYSIS_FRAMES', 30)
        self.min_distance = getattr(settings, 'VISION_MIN_FRAME_DISTANCE_SECONDS', 30)

    def select_frames(self, video_id: str, transcript_segments: List[Any] = None) -> tuple[List[Dict[str, Any]], str]:
        import yt_dlp
        
        t0 = time.time()
        url = f'https://www.youtube.com/watch?v={video_id}'
        local_video_path = os.path.join(self.temp_dir, f'{video_id}_{uuid.uuid4().hex[:8]}.mp4').replace('\\', '/')
        
        ydl_opts = {
            'format': f'bestvideo[height<={self.max_height}][ext=mp4]/bestvideo[height<=480][ext=mp4]/best[height<={self.max_height}]/best',
            'outtmpl': local_video_path,
            'quiet': True,
            'no_warnings': True,
        }

        logger.info('video download started', video_id=video_id)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    actual_height = info.get('height')
                    break
            except Exception as e:
                logger.warning('yt-dlp download failed', attempt=attempt+1, error=str(e))
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise Exception(f'Failed to download video: {str(e)}')

        t1 = time.time()
        logger.info('video_download_completed', duration_s=round(t1-t0, 1), video_id=video_id)

        out_dir = os.path.join(self.temp_dir, f'{video_id}_frames_{uuid.uuid4().hex[:8]}').replace('\\', '/')
        os.makedirs(out_dir, exist_ok=True)

        try:
            logger.info('frame extraction started', out_dir=out_dir)
            fps = 1.0 / self.interval
            ffmpeg_cmd = [
                'ffmpeg', '-y', '-i', local_video_path,
                '-vf', f'fps={fps}', 
                '-fps_mode', 'vfr',
                '-q:v', '2',
                os.path.join(out_dir, 'frame_%05d.jpg').replace('\\', '/')
            ]
            
            subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
            
            t2 = time.time()
            logger.info('frame_sampling_completed', duration_s=round(t2-t1, 1))

            frames = sorted(os.listdir(out_dir))
            logger.info('raw_frames', candidates=len(frames))
            
            # Step 1: Scene Detection and Perceptual Deduplication
            unique_events = []
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
                    unique_events.append({
                        'timestamp': timestamp,
                        'frame_path': frame_path,
                        'frame_hash': str(current_hash),
                        'score': 0.0,
                        'scene_change_score': min(1.0, (current_hash - last_hash) / 30.0) if last_hash else 1.0
                    })
                    last_hash = current_hash
                else:
                    os.remove(frame_path)
                    
            t3 = time.time()
            logger.info('deduplication_completed', duration_s=round(t3-t2, 1), unique_frames=len(unique_events))
            
            # Step 2: Transcript-aware visual scoring
            for event in unique_events:
                ts = event['timestamp']
                transcript_relevance = 0.0
                if transcript_segments:
                    # Look at +/- 15 seconds
                    nearby = [s.text.lower() for s in transcript_segments 
                              if float(s.start_seconds) >= ts - 15 and float(s.start_seconds) <= ts + 15]
                    context_text = " ".join(nearby)
                    
                    matches = sum(1 for kw in VISUAL_KEYWORDS if kw in context_text)
                    transcript_relevance = min(1.0, matches / 2.0)
                
                # Combine scores
                score = (transcript_relevance * 0.50) + (event['scene_change_score'] * 0.50)
                event['score'] = score
            
            # Step 3: Candidate ranking and hard budget (temporal diversity)
            # Sort by score descending
            ranked = sorted(unique_events, key=lambda x: x['score'], reverse=True)
            
            final_selection = []
            for candidate in ranked:
                if len(final_selection) >= self.max_frames:
                    break
                    
                # Check temporal diversity (min distance from already selected)
                too_close = False
                for selected in final_selection:
                    if abs(candidate['timestamp'] - selected['timestamp']) < self.min_distance:
                        # only reject if score isn't massively high
                        if candidate['score'] < 0.8:
                            too_close = True
                            break
                
                if not too_close:
                    final_selection.append(candidate)
            
            # Sort final selection chronologically
            final_selection = sorted(final_selection, key=lambda x: x['timestamp'])
            
            # Cleanup unselected unique frames
            selected_paths = {f['frame_path'] for f in final_selection}
            for event in unique_events:
                if event['frame_path'] not in selected_paths and os.path.exists(event['frame_path']):
                    os.remove(event['frame_path'])
            
            t4 = time.time()
            logger.info('candidate_selection_completed', duration_s=round(t4-t3, 1), selected_frames=len(final_selection))
            
            return final_selection, out_dir

        finally:
            if os.path.exists(local_video_path):
                try:
                    os.remove(local_video_path)
                except Exception:
                    pass
