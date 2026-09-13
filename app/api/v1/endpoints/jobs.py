from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.job import JobResponse
from app.models.job import ProcessingJob

router = APIRouter()

@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return JobResponse(
        id=job.id,
        lecture_id=job.lecture_id,
        status=job.status,
        current_stage=job.current_stage,
        progress=float(job.progress),
        attempt=job.attempt,
        error=job.error_code
    )
