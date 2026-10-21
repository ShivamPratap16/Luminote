"""Transcript, chapters, notes, and artifact API endpoints."""
import os
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from app.db.session import get_db
from app.models.lecture import Lecture
from app.models.transcript import TranscriptSegment
from app.models.chapter import LectureChapter
from app.models.note import Note
from app.models.artifact import Artifact
from app.schemas.notes import NotesResponse, StructuredNotes
from app.services.storage import StorageService
from app.services.pdf import PdfService, PdfGenerationError

router = APIRouter()


# ── Transcript ──────────────────────────────────────────────────

@router.get("/{lecture_id}/transcript")
def get_transcript(lecture_id: str, db: Session = Depends(get_db)):
    """Get timestamped transcript segments for a lecture."""
    lecture = db.query(Lecture).filter(Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")

    segments = (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.lecture_id == lecture_id)
        .order_by(TranscriptSegment.segment_index)
        .all()
    )

    return {
        "lecture_id": str(lecture_id),
        "segments": [
            {
                "start_seconds": float(s.start_seconds),
                "end_seconds": float(s.end_seconds),
                "text": s.text,
            }
            for s in segments
        ],
    }


# ── Chapters ────────────────────────────────────────────────────

@router.get("/{lecture_id}/chapters")
def get_chapters(lecture_id: str, db: Session = Depends(get_db)):
    """Get chapter boundaries for a lecture."""
    lecture = db.query(Lecture).filter(Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")

    chapters = (
        db.query(LectureChapter)
        .filter(LectureChapter.lecture_id == lecture_id)
        .order_by(LectureChapter.chapter_index)
        .all()
    )

    return {
        "lecture_id": str(lecture_id),
        "chapters": [
            {
                "title": ch.title,
                "start_seconds": float(ch.start_seconds),
                "end_seconds": float(ch.end_seconds),
                "source": ch.source,
            }
            for ch in chapters
        ],
    }


# ── Notes ───────────────────────────────────────────────────────

@router.get("/{lecture_id}/notes")
def get_notes(lecture_id: str, db: Session = Depends(get_db)):
    """Get the latest structured notes for a lecture."""
    lecture = db.query(Lecture).filter(Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")

    note = (
        db.query(Note)
        .filter(Note.lecture_id == lecture_id)
        .order_by(Note.version.desc())
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="Notes not yet available")

    return {
        "lecture_id": str(lecture_id),
        "version": note.version,
        "schema_version": note.schema_version,
        "content": note.content_json,
    }


# ── PDF Artifact ────────────────────────────────────────────────

@router.get("/{lecture_id}/pdf")
def download_pdf(lecture_id: str, db: Session = Depends(get_db)):
    """Generate and stream a PDF from stored Notes JSON on demand."""
    lecture = db.query(Lecture).filter(Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")

    note = (
        db.query(Note)
        .filter(Note.lecture_id == lecture_id)
        .order_by(Note.version.desc())
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="Notes not yet available to generate PDF")

    try:
        notes_data = StructuredNotes.model_validate(note.content_json)
        pdf_service = PdfService()
        pdf_path = pdf_service.generate_pdf(
            notes=notes_data,
            source_url=lecture.youtube_url
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {str(e)}")

    def cleanup_pdf():
        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
                # Also try to clean up the parent temp dir if empty
                parent_dir = os.path.dirname(pdf_path)
                if not os.listdir(parent_dir):
                    os.rmdir(parent_dir)
            except Exception:
                pass

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"lecture_{lecture_id}.pdf",
        background=BackgroundTask(cleanup_pdf)
    )
