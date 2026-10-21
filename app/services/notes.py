"""Notes service: context assembly, AI generation, and schema validation.

This service sits between the pipeline orchestrator and the AI provider.
It assembles the context from database records, calls the AI, validates
the response, and returns validated structured notes.
"""
import structlog
import asyncio
from typing import Any, Dict, List, Optional
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.schemas.notes import StructuredNotes
from app.services.ai_provider import (
    AIProvider,
    AIProviderError,
    AIProviderInvalidResponse,
    AIProviderRateLimited,
    AIProviderTimeout,
)
from app.services.chunking import SemanticChunker
from app.models.note import FastNoteChunk
from app.core.config import settings
from datetime import datetime, timezone

logger = structlog.get_logger(__name__)

# Maximum transcript characters to send to the AI. If the transcript exceeds
# this, it will be truncated with a note. This prevents context-window overflows.
MAX_TRANSCRIPT_CHARS = 100_000


class NotesGenerationError(Exception):
    """Raised when notes generation fails after validation."""
    pass


class NotesService:
    """Assembles context, generates notes via AI, and validates output."""

    def __init__(self, ai_provider: AIProvider):
        self.ai_provider = ai_provider

    def build_context(
        self,
        lecture_title: str,
        transcript_segments: List[Dict[str, Any]],
        chapters: List[Dict[str, Any]] | None = None,
        visual_events: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """Build a controlled context object for the AI prompt.
        Handles truncation when transcript exceeds the context budget.
        """
        context = {
            "lecture": {"title": lecture_title},
            "chapters": chapters or [],
            "transcript": [],
            "visual_events": [],
        }

        total_chars = 0
        for seg in transcript_segments:
            text = seg.get("text", "")
            total_chars += len(text)
            if total_chars > MAX_TRANSCRIPT_CHARS:
                context["transcript"].append({
                    "start_seconds": seg.get("start_seconds", 0),
                    "end_seconds": seg.get("end_seconds", 0),
                    "text": "[TRANSCRIPT TRUNCATED - remaining content omitted for context limit]",
                })
                break
            context["transcript"].append({
                "start_seconds": float(seg.get("start_seconds", 0)),
                "end_seconds": float(seg.get("end_seconds", 0)),
                "text": text,
            })

        if visual_events:
            for ve in visual_events:
                v_text = f"[{float(ve.get('timestamp', 0)):.1f} - {ve.get('event_type', 'Visual')}] {ve.get('description', '')}"
                if ve.get("visible_text"):
                    v_text += f" Visible text: {', '.join(ve['visible_text'])}."
                context["visual_events"].append({
                    "timestamp": float(ve.get("timestamp", 0)),
                    "context": v_text,
                    "url": ve.get("frame_storage_key", "")
                })

        return context

    def generate_notes(
        self,
        lecture_title: str,
        transcript_segments: List[Dict[str, Any]],
        chapters: List[Dict[str, Any]] | None = None,
        visual_events: List[Dict[str, Any]] | None = None,
        max_retries: int = getattr(settings, 'AI_MAX_RETRIES', 2),
        db: Session | None = None,
        lecture_id: str | None = None,
    ) -> StructuredNotes:
        """Generate and validate structured notes.
        
        If visual_events are not provided (Fast Notes), it uses chunking and concurrency.
        If visual_events are provided (Enhanced Notes), it uses the legacy monolithic path
        to preserve existing enhanced notes architecture.
        """
        if not visual_events and db and lecture_id:
            # Use Fast Notes Optimization (Chunking + Concurrency)
            return self._generate_fast_notes_chunked(
                db=db,
                lecture_id=lecture_id,
                lecture_title=lecture_title,
                transcript_segments=transcript_segments,
                chapters=chapters,
                max_retries=max_retries,
            )
        else:
            # Use Legacy Monolithic Path (Enhanced Notes)
            return self._generate_monolithic_notes(
                lecture_title=lecture_title,
                transcript_segments=transcript_segments,
                chapters=chapters,
                visual_events=visual_events,
                max_retries=max_retries,
            )

    def _generate_monolithic_notes(
        self,
        lecture_title: str,
        transcript_segments: List[Dict[str, Any]],
        chapters: List[Dict[str, Any]] | None = None,
        visual_events: List[Dict[str, Any]] | None = None,
        max_retries: int = 2,
    ) -> StructuredNotes:
        """Legacy path for generating notes in a single giant API call."""
        import time
        t0 = time.time()
        context = self.build_context(lecture_title, transcript_segments, chapters, visual_events)
        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            logger.info("Generating monolithic notes", attempt=attempt, transcript_segments=len(context["transcript"]))
            try:
                raw_notes, metrics = self.ai_provider.generate_structured_notes(context)
                validated = StructuredNotes.model_validate(raw_notes)
                logger.info(
                    "Monolithic notes validated", 
                    sections=len(validated.sections), 
                    attempt=attempt,
                    input_tokens=metrics.get("input_tokens", 0),
                    output_tokens=metrics.get("output_tokens", 0),
                    duration_s=round(time.time() - t0, 1)
                )
                return validated
            except ValidationError as e:
                logger.warning("AI output failed schema validation", attempt=attempt, errors=str(e))
                last_error = e
            except AIProviderInvalidResponse as e:
                logger.warning("AI returned invalid JSON", attempt=attempt, error=str(e))
                last_error = e
            except AIProviderError as e:
                logger.error("AI provider error during notes generation", attempt=attempt, error=str(e))
                last_error = e

        raise NotesGenerationError(f"Failed to generate monolithic notes after {max_retries} attempts: {last_error}")

    def _generate_fast_notes_chunked(
        self,
        db: Session,
        lecture_id: str,
        lecture_title: str,
        transcript_segments: List[Dict[str, Any]],
        chapters: List[Dict[str, Any]] | None = None,
        max_retries: int = 3,
    ) -> StructuredNotes:
        """Optimized path for Fast Notes using Semantic Chunking & Concurrency."""
        from app.services.ai_provider import create_ai_provider
        
        # Instantiate provider specific to fast notes
        fast_notes_provider = create_ai_provider(settings.FAST_NOTES_PROVIDER)
        
        chunker = SemanticChunker()
        chunks = chunker.create_chunks(transcript_segments, chapters)
        
        if not chunks:
            # Fallback to empty if no transcript
            return StructuredNotes(title=lecture_title, overview="", sections=[], final_takeaways=[])

        # 1. Sync chunks to DB for incremental idempotency
        db_chunks = []
        for c in chunks:
            existing = db.query(FastNoteChunk).filter(
                FastNoteChunk.lecture_id == lecture_id,
                FastNoteChunk.pipeline_version == settings.PIPELINE_VERSION,
                FastNoteChunk.chunk_index == c["chunk_index"],
                FastNoteChunk.content_hash == c["content_hash"]
            ).first()
            if not existing:
                existing = FastNoteChunk(
                    lecture_id=lecture_id,
                    pipeline_version=settings.PIPELINE_VERSION,
                    chunk_index=c["chunk_index"],
                    content_hash=c["content_hash"],
                    status="pending"
                )
                db.add(existing)
            db_chunks.append(existing)
        db.commit()

        # 2. Run LLM concurrently for chunks that are not completed
        import time
        t0 = time.time()
        
        async def process_all_chunks():
            semaphore = asyncio.Semaphore(settings.FAST_NOTES_MAX_CONCURRENCY)
            tasks = []
            for c_def, db_c in zip(chunks, db_chunks):
                tasks.append(self._process_chunk_async(semaphore, fast_notes_provider, db, db_c, c_def, lecture_title, len(chunks), max_retries))
            return await asyncio.gather(*tasks)

        # We must create a new event loop if we are in a sync context (Celery worker).
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        results = loop.run_until_complete(process_all_chunks())
        
        failed = [db_c for db_c in db_chunks if db_c.status != "completed"]
        
        # Gather metrics from DB chunks (note: input/output tokens would need to be stored to report them precisely here, 
        # but we can sum the retries)
        total_retries = sum(db_c.attempt_count - 1 for db_c in db_chunks if db_c.attempt_count > 0)
        
        logger.info(
            "Fast Notes completed",
            fast_notes_provider=settings.FAST_NOTES_PROVIDER,
            fast_notes_model=getattr(fast_notes_provider, "model_name", getattr(fast_notes_provider, "model", "unknown")),
            fast_notes_total_duration_s=round(time.time() - t0, 2),
            fast_notes_total_retries=total_retries,
            fast_notes_failed_chunks=len(failed),
            stage="fast_notes"
        )

        if failed:
            raise NotesGenerationError(f"Fast Notes chunk generation failed. {len(failed)} chunks incomplete.")

        # 3. Deterministic Merge
        return self._merge_chunks(lecture_title, db_chunks)

    async def _process_chunk_async(self, semaphore: asyncio.Semaphore, fast_notes_provider: AIProvider, db: Session, db_chunk: FastNoteChunk, chunk_def: Dict[str, Any], lecture_title: str, total_chunks: int, max_retries: int) -> bool:
        """Process a single chunk with bounded concurrency, retries, and backoff."""
        if db_chunk.status == "completed" and db_chunk.output_json:
            logger.info("Chunk already completed", chunk_index=db_chunk.chunk_index)
            return True

        async with semaphore:
            # Build chunk-specific context
            context = {
                "lecture": {"title": lecture_title, "chunk_info": f"Part {db_chunk.chunk_index + 1} of {total_chunks}"},
                "chapters": [{"title": chunk_def["chapter_title"]}] if chunk_def["chapter_title"] else [],
                "transcript": chunk_def["segments"],
                "visual_events": [],
            }

            for attempt in range(db_chunk.attempt_count + 1, db_chunk.attempt_count + max_retries + 1):
                db_chunk.status = "processing"
                db_chunk.attempt_count = attempt
                db.commit()

                logger.info("Processing chunk", chunk_index=db_chunk.chunk_index, attempt=attempt)
                import time
                t_attempt = time.time()
                try:
                    # Run the sync AI call in a thread pool to not block asyncio event loop
                    raw_notes, metrics = await asyncio.to_thread(fast_notes_provider.generate_structured_notes, context)
                    validated = StructuredNotes.model_validate(raw_notes)
                    
                    db_chunk.output_json = validated.model_dump()
                    db_chunk.status = "completed"
                    db_chunk.error_message = None
                    db.commit()
                    
                    logger.info(
                        "Chunk generated successfully",
                        stage="fast_notes",
                        provider=settings.FAST_NOTES_PROVIDER,
                        model=getattr(fast_notes_provider, "model_name", getattr(fast_notes_provider, "model", "unknown")),
                        chunk_index=db_chunk.chunk_index,
                        input_tokens=metrics.get("input_tokens", 0),
                        output_tokens=metrics.get("output_tokens", 0),
                        duration_s=round(time.time() - t_attempt, 1),
                        retry_count=attempt - 1,
                        status="success"
                    )
                    
                    return True

                except (ValidationError, AIProviderInvalidResponse) as e:
                    logger.warning("Chunk validation failed", chunk_index=db_chunk.chunk_index, error=str(e), stage="fast_notes", status="failure")
                    db_chunk.error_message = f"Validation Error: {str(e)}"
                    db.commit()
                    # Short backoff for application errors
                    await asyncio.sleep(2)
                
                except (AIProviderRateLimited, AIProviderTimeout) as e:
                    logger.warning("Chunk API rate limited/timeout", chunk_index=db_chunk.chunk_index, error=str(e), stage="fast_notes", status="failure")
                    db_chunk.error_message = f"API Error: {str(e)}"
                    db.commit()
                    # Exponential backoff for network/rate limits
                    await asyncio.sleep(2 ** attempt)
                
                except AIProviderError as e:
                    logger.error("Chunk API error", chunk_index=db_chunk.chunk_index, error=str(e), stage="fast_notes", status="failure")
                    db_chunk.error_message = f"API Error: {str(e)}"
                    db.commit()
                    await asyncio.sleep(2 ** attempt)

            db_chunk.status = "failed"
            db.commit()
            return False

    def _merge_chunks(self, lecture_title: str, db_chunks: List[FastNoteChunk]) -> StructuredNotes:
        """Deterministically merge the successful JSON outputs of all chunks."""
        sections = []
        all_takeaways = []
        topic_summaries = []

        # Ensure ordered by chunk_index
        sorted_chunks = sorted(db_chunks, key=lambda c: c.chunk_index)

        for c in sorted_chunks:
            if not c.output_json:
                continue
            chunk_notes = StructuredNotes.model_validate(c.output_json)
            sections.extend(chunk_notes.sections)
            all_takeaways.extend(chunk_notes.final_takeaways)
            
            # Extract topics for the synthesized overview
            for sec in chunk_notes.sections:
                if sec.title not in topic_summaries:
                    topic_summaries.append(sec.title)

        # Deduplicate takeaways (preserving order)
        seen_takeaways = set()
        unique_takeaways = []
        for t in all_takeaways:
            if t not in seen_takeaways:
                seen_takeaways.add(t)
                unique_takeaways.append(t)

        # Synthesize overview deterministically
        if topic_summaries:
            overview = f"This lecture covers key topics including: {', '.join(topic_summaries[:10])}. It is broken down into {len(sections)} detailed sections."
        else:
            overview = "No detailed sections were extracted from this lecture."

        return StructuredNotes(
            title=lecture_title,
            overview=overview,
            sections=sections,
            final_takeaways=unique_takeaways
        )
