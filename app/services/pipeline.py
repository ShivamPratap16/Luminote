"""Processing pipeline orchestrator.

This module owns the end-to-end processing flow for a lecture job.
Each stage is independently callable and checks whether prior work
already exists before recomputing. This enables safe retries.

The orchestrator is called by the Celery worker task but contains
no Celery-specific code. It is independently testable.
"""
import structlog
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone

from app.models.lecture import Lecture
from app.models.job import ProcessingJob
from app.models.transcript import TranscriptSegment
from app.models.visual_event import VisualEvent
from app.models.chapter import LectureChapter
from app.models.note import Note
from app.models.artifact import Artifact
from app.schemas.notes import StructuredNotes

from app.services.youtube import YouTubeService, YouTubeSourceError
from app.services.media import MediaService, MediaPreparationError
from app.services.transcription import TranscriptionService, TranscriptionError
from app.services.notes import NotesService, NotesGenerationError
from app.services.pdf import PdfService, PdfGenerationError
from app.services.storage import StorageService
from app.services.ai_provider import create_ai_provider

logger = structlog.get_logger(__name__)

# Progress weights from the spec
STAGE_PROGRESS = {
    "metadata": 5,
    "media_preparation": 15,
    "transcription": 35,
    "chapters": 45,
    "note_generation": 75,
    "pdf_generation": 95,
    "completed": 100,
}


class PipelineError(Exception):
    """Base pipeline error."""
    def __init__(self, message: str, error_code: str, is_permanent: bool = False):
        super().__init__(message)
        self.error_code = error_code
        self.is_permanent = is_permanent


class PipelineOrchestrator:
    """Orchestrates the full lecture processing pipeline.

    Each stage:
    1. Checks if work already exists (idempotency)
    2. Performs the work
    3. Persists results transactionally
    4. Updates job progress

    The orchestrator does not catch exceptions internally; the caller
    (worker task) is responsible for error handling and retry decisions.
    """

    def __init__(
        self,
        db: Session,
        youtube_service: Optional[YouTubeService] = None,
        media_service: Optional[MediaService] = None,
        transcription_service: Optional[TranscriptionService] = None,
        notes_service: Optional[NotesService] = None,
        pdf_service: Optional[PdfService] = None,
        storage_service: Optional[StorageService] = None,
    ):
        self.db = db
        self.youtube = youtube_service or YouTubeService()
        self.media = media_service or MediaService()
        self.transcription = transcription_service or TranscriptionService()
        self.pdf = pdf_service or PdfService()
        self.storage = storage_service or StorageService()

        # Notes service requires AI provider; create lazily
        self._notes_service = notes_service

    @property
    def notes(self) -> NotesService:
        if self._notes_service is None:
            ai_provider = create_ai_provider()
            self._notes_service = NotesService(ai_provider)
        return self._notes_service

    def _update_job(self, job: ProcessingJob, stage: str, status: str = "processing"):
        """Update job state in the database."""
        job.status = status
        job.current_stage = stage
        job.progress = STAGE_PROGRESS.get(stage, 0)
        job.updated_at = datetime.now(timezone.utc)
        if status == "processing" and not job.started_at:
            job.started_at = datetime.now(timezone.utc)
        if status == "completed":
            job.completed_at = datetime.now(timezone.utc)
        self.db.commit()
        logger.info("Job state updated", job_id=str(job.id), stage=stage, status=status)

    def run(self, job_id: str) -> None:
        import time
        job = self.db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if not job:
            raise PipelineError("Job not found", "INTERNAL_ERROR", is_permanent=True)

        lecture = self.db.query(Lecture).filter(Lecture.id == job.lecture_id).first()
        if not lecture:
            raise PipelineError("Lecture not found", "INTERNAL_ERROR", is_permanent=True)

        log = logger.bind(job_id=str(job.id), lecture_id=str(lecture.id))
        log.info("Starting pipeline")

        audio_path = None
        t_start = time.time()
        
        try:
            # Stage 1: Metadata
            t0 = time.time()
            self._update_job(job, "metadata")
            self._stage_metadata(lecture, log)
            log.info("metrics", stage="metadata", duration_s=round(time.time()-t0, 1))

            # Stage 1.5/2/3: Transcript
            t0 = time.time()
            self._update_job(job, "transcript_acquisition")
            captions_extracted = self._stage_transcript_acquisition(lecture, log)

            if captions_extracted:
                log.info("Stage media_preparation skipped reason=captions_available")
                log.info("Stage transcription skipped reason=captions_available")
            else:
                self._update_job(job, "media_preparation")
                audio_path = self._stage_media(lecture, log)
                self._update_job(job, "transcription")
                self._stage_transcription(lecture, audio_path, log)
            log.info("metrics", stage="transcript_pipeline", duration_s=round(time.time()-t0, 1))

            # FAST PATH: Generate Basic Notes immediately
            t0 = time.time()
            self._update_job(job, "chapters")
            self._stage_chapters(lecture, log)
            
            self._update_job(job, "note_generation")
            note = self._stage_notes(lecture, log)
            
            self._update_job(job, "pdf_generation")
            self._stage_pdf(lecture, note, log)
            log.info("metrics", stage="fast_notes", duration_s=round(time.time()-t0, 1))

            # Stage 3.5: Visual Analysis (ENHANCED PATH)
            t0 = time.time()
            self._update_job(job, "visual_analysis")
            visuals_added = self._stage_visual_analysis(job, lecture, log)
            log.info("metrics", stage="visual_analysis", duration_s=round(time.time()-t0, 1))

            # If visuals were successfully added, generate Enhanced Notes
            if visuals_added:
                log.info("Visuals were added, generating Enhanced Notes")
                t0 = time.time()
                self._update_job(job, "note_generation_enhanced")
                note_enhanced = self._stage_notes(lecture, log, force_regenerate=True)
                
                self._update_job(job, "pdf_generation_enhanced")
                self._stage_pdf(lecture, note_enhanced, log)
                log.info("metrics", stage="enhanced_notes", duration_s=round(time.time()-t0, 1))

            # Done
            lecture.status = "completed"
            self.db.commit()
            self._update_job(job, "completed", status="completed")
            log.info("metrics", stage="total", duration_s=round(time.time()-t_start, 1))
            log.info("Pipeline completed successfully")

        finally:
            if audio_path:
                MediaService.cleanup_file(audio_path)

    # ── Stage implementations ──────────────────────────────────────

    def _stage_metadata(self, lecture: Lecture, log) -> None:
        """Fetch and persist video metadata. Skips if title already set."""
        if lecture.title:
            log.info("Metadata already present, skipping")
            return

        log.info("Fetching metadata")
        try:
            meta = self.youtube.fetch_metadata(lecture.youtube_video_id)
        except YouTubeSourceError as e:
            raise PipelineError(str(e), "SOURCE_UNAVAILABLE", is_permanent=True)

        lecture.title = meta.title
        lecture.channel_name = meta.channel_name
        lecture.duration_seconds = meta.duration_seconds
        lecture.thumbnail_url = meta.thumbnail_url
        lecture.description = meta.description
        lecture.status = "processing"
        self.db.commit()
        log.info("Metadata persisted", title=meta.title)

    def _stage_transcript_acquisition(self, lecture: Lecture, log) -> bool:
        """Try to fetch captions from YouTube to bypass audio download + whisper."""
        """Extract existing captions to bypass media and Whisper stages.
        Returns True if successful or skipped due to existing segments, False otherwise."""
        existing = (
            self.db.query(TranscriptSegment)
            .filter(TranscriptSegment.lecture_id == lecture.id)
            .count()
        )
        if existing > 0:
            log.info("Transcript segments already exist, skipping caption extraction", count=existing)
            return True

        log.info("Attempting YouTube caption extraction")
        captions = self.youtube.fetch_captions(lecture.youtube_video_id)
        if not captions:
            log.info("No valid captions available")
            return False

        # Persist all segments
        db_segments = []
        for idx, cap in enumerate(captions):
            db_segments.append(TranscriptSegment(
                lecture_id=lecture.id,
                segment_index=idx,
                start_seconds=cap["start_seconds"],
                end_seconds=cap["end_seconds"],
                text=cap["text"],
            ))
        self.db.add_all(db_segments)
        self.db.commit()
        log.info("Caption extraction completed source=youtube", count=len(db_segments))
        return True

    def _stage_media(self, lecture: Lecture, log) -> str:
        """Download and prepare audio. Returns the local audio file path."""
        log.info("Preparing audio")
        try:
            result = self.media.prepare_audio(lecture.youtube_video_id)
        except MediaPreparationError as e:
            raise PipelineError(str(e), "SOURCE_UNAVAILABLE")
        log.info("Audio prepared", duration=result.duration_seconds)
        return result.file_path

    def _stage_transcription(self, lecture: Lecture, audio_path: str, log) -> None:
        """Transcribe audio and persist segments. Skips if segments exist."""
        existing = (
            self.db.query(TranscriptSegment)
            .filter(TranscriptSegment.lecture_id == lecture.id)
            .count()
        )
        if existing > 0:
            log.info("Transcript segments already exist, skipping", count=existing)
            return

        log.info("Starting transcription")
        try:
            segments = self.transcription.transcribe(audio_path)
        except TranscriptionError as e:
            raise PipelineError(str(e), "TRANSCRIPTION_FAILED")

        # Persist all segments in a single transaction
        db_segments = []
        for seg in segments:
            db_segments.append(TranscriptSegment(
                lecture_id=lecture.id,
                segment_index=seg.segment_index,
                start_seconds=seg.start_seconds,
                end_seconds=seg.end_seconds,
                text=seg.text,
            ))
        self.db.add_all(db_segments)
        self.db.commit()
        log.info("Transcript segments persisted", count=len(db_segments))

    
    def _stage_visual_analysis(self, job: ProcessingJob, lecture: Lecture, log) -> None:
        from app.services.frame_selection import FrameSelectionService
        from app.services.youtube_acquisition import YouTubeAcquisitionBlocked
        from app.services.vision import VisionService
        from app.models.visual_event import VisualEvent
        from app.core.config import settings
        import shutil
        import os
        import asyncio
        import time

        if not getattr(settings, 'VISION_ENABLED', True):
            log.info("Visual analysis disabled via config")
            return

        frame_service = FrameSelectionService()
        vision_service = VisionService()

        log.info("Starting frame selection")
        out_dir = None
        
        t0 = time.time()
        transcript_segments = lecture.transcript_segments

        try:
            candidates, out_dir = frame_service.select_frames(lecture.youtube_video_id, transcript_segments)
        except YouTubeAcquisitionBlocked as e:
            log.error("Frame selection blocked by YouTube", error_type="YOUTUBE_ACQUISITION_BLOCKED", error=str(e))
            self._update_job(job, "visual_analysis", status="blocked")
            return
        except Exception as e:
            log.warning("Frame selection failed, skipping visual analysis", error=str(e))
            self._update_job(job, "visual_analysis", status="retryable_failed")
            return

        try:
            to_process = []
            for cand in candidates:
                existing = self.db.query(VisualEvent).filter(
                    VisualEvent.lecture_id == lecture.id,
                    VisualEvent.timestamp == cand['timestamp'],
                    VisualEvent.frame_hash == cand['frame_hash']
                ).first()
                if existing:
                    log.info("Visual event already processed, skipping", timestamp=cand['timestamp'])
                else:
                    to_process.append(cand)

            if not to_process:
                return

            batch_size = getattr(settings, 'VISION_MAX_IMAGES_PER_REQUEST', 5)
            concurrency = getattr(settings, 'VISION_CONCURRENCY', 4)
            
            batches = [to_process[i:i + batch_size] for i in range(0, len(to_process), batch_size)]
            log.info('vision_batches_prepared', batches=len(batches), total_frames=len(to_process))
            
            semaphore = asyncio.Semaphore(concurrency)
            
            async def process_batch(batch):
                async with semaphore:
                    try:
                        return await vision_service.analyze_frames_batch(batch, transcript_segments)
                    except Exception as e:
                        log.warning("Batch failed", error=str(e))
                        return []
                        
            async def run_all():
                tasks = [process_batch(b) for b in batches]
                return await asyncio.gather(*tasks)

            t1 = time.time()
            results = asyncio.run(run_all())
            t2 = time.time()
            log.info('vision_api_completed', duration_s=round(t2-t1, 1))

            new_events_count = 0
            for batch_res in results:
                for item in batch_res:
                    try:
                        storage_key = None
                        try:
                            stored = self.storage.store_artifact(
                                local_path=item['frame_path'],
                                lecture_id=str(lecture.id),
                                artifact_type="frames",
                                extension="jpg"
                            )
                            storage_key = stored.storage_key
                        except Exception as e:
                            log.warning("Failed to persist frame to storage", error=str(e))
                        
                        event = VisualEvent(
                            lecture_id=lecture.id,
                            timestamp=item['timestamp'],
                            frame_hash=item['frame_hash'],
                            event_type=item.get('event_type', 'unknown'),
                            description=item.get('description', ''),
                            visible_text=item.get('visible_text', []),
                            key_information=item.get('key_information', []),
                            frame_storage_key=storage_key
                        )
                        self.db.add(event)
                        new_events_count += 1
                    except Exception as e:
                        log.error("Failed to parse visual event", error=str(e))
            
            self.db.commit()
            log.info('visual_analysis_total', duration_s=round(time.time()-t0, 1), new_events=new_events_count)
            
            if new_events_count > 0:
                return True
                
            return False

        finally:
            if out_dir and os.path.exists(out_dir):
                try:
                    shutil.rmtree(out_dir)
                    log.info("cleanup completed", directory=out_dir)
                except Exception as e:
                    log.warning("Failed to clean up extracted frames", error=str(e))

    def _stage_chapters(self, lecture: Lecture, log) -> None:
        """Persist chapter boundaries. Uses YouTube chapters if available,
        otherwise creates a single derived chapter spanning the whole lecture."""
        existing = (
            self.db.query(LectureChapter)
            .filter(LectureChapter.lecture_id == lecture.id)
            .count()
        )
        if existing > 0:
            log.info("Chapters already exist, skipping", count=existing)
            return

        # Try to get YouTube chapters from metadata (already fetched)
        try:
            meta = self.youtube.fetch_metadata(lecture.youtube_video_id)
            youtube_chapters = meta.chapters
        except Exception:
            youtube_chapters = []

        if youtube_chapters:
            chapters = []
            for idx, ch in enumerate(youtube_chapters):
                chapters.append(LectureChapter(
                    lecture_id=lecture.id,
                    chapter_index=idx,
                    title=ch["title"],
                    start_seconds=ch["start_seconds"],
                    end_seconds=ch["end_seconds"],
                    source="youtube",
                ))
            self.db.add_all(chapters)
            self.db.commit()
            log.info("YouTube chapters persisted", count=len(chapters))
        else:
            # Create a single derived chapter
            duration = lecture.duration_seconds or 0
            chapter = LectureChapter(
                lecture_id=lecture.id,
                chapter_index=0,
                title=lecture.title or "Full Lecture",
                start_seconds=0,
                end_seconds=duration,
                source="derived",
            )
            self.db.add(chapter)
            self.db.commit()
            log.info("Derived single chapter created")

    def _stage_notes(self, lecture: Lecture, log) -> Note:
        """Generate structured notes via AI. Returns the Note record.
        Skips if notes already exist for this lecture."""
        existing = (
            self.db.query(Note)
            .filter(Note.lecture_id == lecture.id)
            .order_by(Note.version.desc())
            .first()
        )
        if existing:
            log.info("Notes already exist, skipping", version=existing.version)
            return existing

        # Load transcript segments for context
        segments = (
            self.db.query(TranscriptSegment)
            .filter(TranscriptSegment.lecture_id == lecture.id)
            .order_by(TranscriptSegment.segment_index)
            .all()
        )
        transcript_data = [
            {
                "start_seconds": float(s.start_seconds),
                "end_seconds": float(s.end_seconds),
                "text": s.text,
            }
            for s in segments
        ]

        # Load chapters for context
        chapters = (
            self.db.query(LectureChapter)
            .filter(LectureChapter.lecture_id == lecture.id)
            .order_by(LectureChapter.chapter_index)
            .all()
        )
        chapter_data = [
            {
                "title": ch.title,
                "start_seconds": float(ch.start_seconds),
                "end_seconds": float(ch.end_seconds),
            }
            for ch in chapters
        ]

        log.info("Generating structured notes")
        try:
            validated_notes: StructuredNotes = self.notes.generate_notes(
                lecture_title=lecture.title or "Untitled",
                transcript_segments=transcript_data,
                chapters=chapter_data,
            )
        except NotesGenerationError as e:
            raise PipelineError(str(e), "AI_GENERATION_FAILED")

        # Persist
        note = Note(
            lecture_id=lecture.id,
            version=1,
            schema_version="1.0",
            content_json=validated_notes.model_dump(),
        )
        self.db.add(note)
        self.db.commit()
        self.db.refresh(note)
        log.info("Structured notes persisted", note_id=str(note.id))
        return note

    def _stage_pdf(self, lecture: Lecture, note: Note, log) -> None:
        """Generate PDF from notes, store it, and create artifact record.
        Skips if a PDF artifact already exists for this note."""
        existing = (
            self.db.query(Artifact)
            .filter(
                Artifact.lecture_id == lecture.id,
                Artifact.note_id == note.id,
                Artifact.type == "pdf",
            )
            .first()
        )
        if existing:
            log.info("PDF artifact already exists, skipping")
            return

        # Reconstruct StructuredNotes from the stored JSON
        notes_data = StructuredNotes.model_validate(note.content_json)

        log.info("Generating PDF")
        try:
            pdf_path = self.pdf.generate_pdf(
                notes=notes_data,
                source_url=lecture.youtube_url,
            )
        except PdfGenerationError as e:
            raise PipelineError(str(e), "PDF_GENERATION_FAILED")

        # Store in object storage
        stored = self.storage.store_artifact(
            local_path=pdf_path,
            lecture_id=str(lecture.id),
            artifact_type="pdf",
            extension="pdf",
        )

        # Create artifact record
        artifact = Artifact(
            lecture_id=lecture.id,
            note_id=note.id,
            type="pdf",
            storage_key=stored.storage_key,
            mime_type="application/pdf",
            size_bytes=stored.size_bytes,
            checksum=stored.checksum,
        )
        self.db.add(artifact)
        self.db.commit()

        # Clean up temp PDF
        MediaService.cleanup_file(pdf_path)
        log.info("PDF artifact stored", artifact_id=str(artifact.id), size=stored.size_bytes)












