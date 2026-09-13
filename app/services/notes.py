"""Notes service: context assembly, AI generation, and schema validation.

This service sits between the pipeline orchestrator and the AI provider.
It assembles the context from database records, calls the AI, validates
the response, and returns validated structured notes.
"""
import structlog
from typing import Any, Dict, List, Optional
from pydantic import ValidationError
from app.schemas.notes import StructuredNotes
from app.services.ai_provider import AIProvider, AIProviderError, AIProviderInvalidResponse

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
        Does not pass raw database records to the model.
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
                # Condense visual event for text AI
                # e.g. [14:20 - Diagram] Shows relationship...
                v_text = f"[{float(ve.get('timestamp', 0)):.1f} - {ve.get('event_type', 'Visual')}] {ve.get('description', '')}"
                if ve.get("visible_text"):
                    v_text += f" Visible text: {', '.join(ve['visible_text'])}."
                context["visual_events"].append({
                    "timestamp": float(ve.get("timestamp", 0)),
                    "context": v_text
                })

        return context

    def generate_notes(
        self,
        lecture_title: str,
        transcript_segments: List[Dict[str, Any]],
        chapters: List[Dict[str, Any]] | None = None,
        visual_events: List[Dict[str, Any]] | None = None,
        max_retries: int = 2,
    ) -> StructuredNotes:
        """Generate and validate structured notes."""
        context = self.build_context(lecture_title, transcript_segments, chapters, visual_events)

        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            logger.info(
                "Generating notes",
                attempt=attempt,
                max_retries=max_retries,
                transcript_segments=len(context["transcript"]),
            )
            try:
                raw_notes = self.ai_provider.generate_structured_notes(context)
                validated = StructuredNotes.model_validate(raw_notes)
                logger.info(
                    "Notes generated and validated",
                    sections=len(validated.sections),
                    attempt=attempt,
                )
                return validated

            except ValidationError as e:
                logger.warning(
                    "AI output failed schema validation",
                    attempt=attempt,
                    errors=str(e),
                )
                last_error = e

            except AIProviderInvalidResponse as e:
                logger.warning(
                    "AI returned invalid JSON",
                    attempt=attempt,
                    error=str(e),
                )
                last_error = e

            except AIProviderError as e:
                logger.error(
                    "AI provider error during notes generation",
                    attempt=attempt,
                    error=str(e),
                )
                last_error = e

        raise NotesGenerationError(
            f"Failed to generate valid notes after {max_retries} attempts: {last_error}"
        )



