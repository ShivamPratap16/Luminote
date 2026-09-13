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
        """Run the full pipeline for a job.

        This is the main entry point called by the worker.
        """
        job = self.db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if not job:
            raise PipelineError("Job not found", "INTERNAL_ERROR", is_permanent=True)

        lecture = self.db.query(Lecture).filter(Lecture.id == job.lecture_id).first()
        if not lecture:
            raise PipelineError("Lecture not found", "INTERNAL_ERROR", is_permanent=True)

        log = logger.bind(job_id=str(job.id), lecture_id=str(lecture.id))
        log.info("Starting pipeline")

        audio_path: Optional[str] = None
        try:
            # Stage 1: Metadata
            self._update_job(job, "metadata")
            self._stage_metadata(lecture, log)

            # Stage 1.5: Caption Extraction
            self._update_job(job, "caption_extraction")
            captions_extracted = self._stage_caption_extraction(lecture, log)

            if captions_extracted:
                log.info("Stage media_preparation skipped reason=captions_available")
                log.info("Stage transcription skipped reason=captions_available")
            else:
                # Stage 2: Media preparation
                self._update_job(job, "media_preparation")
                audio_path = self._stage_media(lecture, log)

                # Stage 3: Transcription
                self._update_job(job, "transcription")
                self._stage_transcription(lecture, audio_path, log)

            # Stage 3.5: Visual Analysis
            self._update_job(job, "visual_analysis")
            self._stage_visual_analysis(lecture, log)

            # Stage 4: Chapters
            self._update_job(job, "chapters")
            self._stage_chapters(lecture, log)

            # Stage 5: Note generation
            self._update_job(job, "note_generation")
            note = self._stage_notes(lecture, log)

            # Stage 6: PDF generation
            self._update_job(job, "pdf_generation")
            self._stage_pdf(lecture, note, log)

            # Done
            lecture.status = "completed"
            self.db.commit()
            self._update_job(job, "completed", status="completed")
            log.info("Pipeline completed successfully")

        finally:
            # Always clean up temp audio
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

    def _stage_caption_extraction(self, lecture: Lecture, log) -> bool:
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

    
    def _stage_visual_analysis(self, lecture: Lecture, log) -> None:
        from app.services.frame_selection import FrameSelectionService
        from app.services.vision import VisionService
        from app.models.visual_event import VisualEvent

        frame_service = FrameSelectionService()
        vision_service = VisionService()

        # Extract frames and find visual changes
        log.info("Starting frame selection")
        try:
            candidates, out_dir = frame_service.select_frames(lecture.youtube_video_id)
        except Exception as e:
            log.warning("Frame selection failed, skipping visual analysis", error=str(e))
            return

        for cand in candidates:
            # Check if this exact event is already processed (Idempotency)
            existing = self.db.query(VisualEvent).filter(
                VisualEvent.lecture_id == lecture.id,
                VisualEvent.timestamp == cand['timestamp'],
                VisualEvent.frame_hash == cand['frame_hash']
            ).first()
            if existing:
                log.info("Visual event already processed, skipping", timestamp=cand['timestamp'])
                continue

            log.info("Analyzing frame with NVIDIA Vision", timestamp=cand['timestamp'])
            
            # Fetch nearby transcript text for context
            nearby_segments = self.db.query(TranscriptSegment).filter(
                TranscriptSegment.lecture_id == lecture.id,
                TranscriptSegment.start_seconds >= float(cand['timestamp']) - 30,
                TranscriptSegment.end_seconds <= float(cand['timestamp']) + 30
            ).all()
            context_text = " ".join([s.text for s in nearby_segments])

            try:
                analysis = vision_service.analyze_frame(cand['frame_path'], context=context_text)
                if not analysis:
                    continue
                
                # Store the frame image in storage for provenance
                storage_key = None
                try:
                    stored = self.storage.store_artifact(
                        local_path=cand['frame_path'],
                        lecture_id=str(lecture.id),
                        artifact_type="frames",
                        extension="jpg"
                    )
                    storage_key = stored.storage_key
                except Exception as e:
                    log.warning("Failed to persist frame to storage", error=str(e))
                
                # Save to DB
                event = VisualEvent(
                    lecture_id=lecture.id,
                    timestamp=cand['timestamp'],
                    frame_hash=cand['frame_hash'],
                    event_type=analysis.event_type,
                    description=analysis.description,
                    visible_text=analysis.visible_text,
                    key_information=analysis.key_information,
                    frame_storage_key=storage_key
                )
                self.db.add(event)
                self.db.commit()
                log.info("Visual event persisted", timestamp=cand['timestamp'], event_type=analysis.event_type)
            except Exception as e:
                log.error("Failed to analyze/persist visual event", timestamp=cand['timestamp'], error=str(e))
                # For V1, we log and continue to the next frame rather than failing the whole pipeline
                
        # Clean up extracted frames
        import shutil
        import os
        try:
            if os.path.exists(out_dir):
                shutil.rmtree(out_dir)
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


