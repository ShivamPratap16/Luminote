"""Celery worker tasks.

The task is a thin wrapper that creates a database session, instantiates
the PipelineOrchestrator, and handles error classification for retries.
All business logic lives in the pipeline orchestrator.
"""
from app.worker.celery_app import celery_app
import structlog
from app.db.session import SessionLocal
from app.models.job import ProcessingJob
from app.services.pipeline import PipelineOrchestrator, PipelineError
from datetime import datetime, timezone

logger = structlog.get_logger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def process_lecture_job(self, job_id: str):
    """Process a lecture through the full pipeline.

    Error handling strategy:
    - PipelineError with is_permanent=True → mark as failed_permanent, no retry
    - PipelineError (transient) → mark as failed_transient, retry with backoff
    - Unexpected exceptions → mark as failed_transient, retry with backoff
    - Max retries exceeded → mark as failed_permanent
    """
    log = logger.bind(job_id=job_id, celery_task_id=self.request.id)
    log.info("Worker picked up job")

    db = SessionLocal()
    try:
        # Increment attempt counter
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if not job:
            log.error("Job not found in database")
            return
        job.attempt = (job.attempt or 0) + 1
        db.commit()

        # Run the pipeline
        orchestrator = PipelineOrchestrator(db=db)
        orchestrator.run(job_id)

    except PipelineError as exc:
        log.error(
            "Pipeline error",
            error_code=exc.error_code,
            is_permanent=exc.is_permanent,
            error=str(exc),
            stage=_get_current_stage(db, job_id),
        )
        _mark_job_failed(db, job_id, exc.error_code, str(exc), exc.is_permanent)

        if not exc.is_permanent:
            # Exponential backoff: 10s, 60s, 300s
            countdown = min(10 * (3 ** self.request.retries), 300)
            raise self.retry(exc=exc, countdown=countdown)

    except Exception as exc:
        log.error(
            "Unexpected error in worker",
            error=str(exc),
            stage=_get_current_stage(db, job_id),
            exc_info=True,
        )
        _mark_job_failed(db, job_id, "INTERNAL_ERROR", str(exc), is_permanent=False)

        countdown = min(10 * (3 ** self.request.retries), 300)
        raise self.retry(exc=exc, countdown=countdown)

    finally:
        db.close()


def _mark_job_failed(
    db, job_id: str, error_code: str, error_message: str, is_permanent: bool
):
    """Update job record with failure information."""
    try:
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if job:
            job.status = "failed_permanent" if is_permanent else "failed_transient"
            job.error_code = error_code
            job.error_message = error_message[:2000]  # Truncate long errors
            job.updated_at = datetime.now(timezone.utc)
            db.commit()
    except Exception:
        logger.error("Failed to update job failure state", job_id=job_id, exc_info=True)


def _get_current_stage(db, job_id: str) -> str:
    """Read current stage for logging context."""
    try:
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        return job.current_stage if job else "unknown"
    except Exception:
        return "unknown"
