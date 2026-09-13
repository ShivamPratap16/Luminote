"""Lecture creation and retrieval endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.schemas.lecture import LectureCreate, LectureCreateResponse, LectureResponse
from app.models.lecture import Lecture
from app.models.job import ProcessingJob
from app.services.youtube import YouTubeService, YouTubeValidationError
from app.worker.tasks import process_lecture_job

router = APIRouter()


@router.post("", response_model=LectureCreateResponse, status_code=status.HTTP_201_CREATED)
def create_lecture(lecture_in: LectureCreate, db: Session = Depends(get_db)):
    """Create a lecture from a YouTube URL and enqueue processing.

    - Validates and normalizes the URL
    - Creates or reuses the lecture record (deduplication by video ID)
    - Creates a new processing job
    - Dispatches the job to the Celery worker
    - Returns immediately
    """
    # Validate and normalize
    try:
        video_id = YouTubeService.extract_video_id(str(lecture_in.youtube_url))
    except YouTubeValidationError:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "INVALID_YOUTUBE_URL",
                    "message": "The supplied URL is not a supported YouTube URL.",
                }
            },
        )

    normalized_url = YouTubeService.normalize_url(video_id)

    # Deduplication: reuse existing lecture if same video ID
    lecture = db.query(Lecture).filter(Lecture.youtube_video_id == video_id).first()
    if not lecture:
        lecture = Lecture(
            youtube_video_id=video_id,
            youtube_url=normalized_url,
            status="pending",
        )
        db.add(lecture)
        db.commit()
        db.refresh(lecture)

    # Create a new processing job
    job = ProcessingJob(
        lecture_id=lecture.id,
        status="queued",
        current_stage="created",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Dispatch to Celery (non-blocking)
    process_lecture_job.delay(str(job.id))

    return LectureCreateResponse(
        lecture_id=lecture.id,
        job_id=job.id,
        status=job.status,
    )


@router.get("", response_model=List[LectureResponse])
def list_lectures(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List lectures with pagination."""
    offset = (page - 1) * page_size
    lectures = (
        db.query(Lecture)
        .order_by(Lecture.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    return lectures


@router.get("/{lecture_id}", response_model=LectureResponse)
def get_lecture(lecture_id: str, db: Session = Depends(get_db)):
    """Get a single lecture by ID."""
    lecture = db.query(Lecture).filter(Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "LECTURE_NOT_FOUND",
                    "message": "Lecture not found.",
                }
            },
        )
    return lecture
