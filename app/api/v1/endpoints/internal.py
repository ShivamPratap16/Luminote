from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.lecture import Lecture
from app.models.job import ProcessingJob
from app.worker.tasks import process_lecture_job
from app.services.youtube import YouTubeService
import os
import shutil
from app.core.config import settings

router = APIRouter()

class LocalVideoRequest(BaseModel):
    youtube_video_id: str
    local_path: str

@router.post("/process-local-video")
def process_local_video(request: LocalVideoRequest, db: Session = Depends(get_db)):
    if not os.path.exists(request.local_path):
        raise HTTPException(status_code=400, detail="Local file not found")
        
    cache_dir = getattr(settings, 'YOUTUBE_MEDIA_CACHE_DIR', './data/youtube-cache')
    video_dir = os.path.join(cache_dir, request.youtube_video_id)
    os.makedirs(video_dir, exist_ok=True)
    dest = os.path.join(video_dir, "video.mp4")
    
    shutil.copy(request.local_path, dest)
    
    lecture = db.query(Lecture).filter(Lecture.youtube_video_id == request.youtube_video_id).first()
    if not lecture:
        lecture = Lecture(
            youtube_video_id=request.youtube_video_id,
            youtube_url=YouTubeService.normalize_url(request.youtube_video_id),
            status="pending",
        )
        db.add(lecture)
        db.commit()
        db.refresh(lecture)
        
    job = ProcessingJob(
        lecture_id=lecture.id,
        status="queued",
        current_stage="created",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    process_lecture_job.delay(str(job.id))

    return {"message": "Local video cached and job started", "job_id": job.id}
