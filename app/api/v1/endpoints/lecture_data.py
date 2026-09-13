"""Transcript, chapters, notes, and artifact API endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
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

@router.get("/{lecture_id}/artifacts/pdf")
def get_pdf_artifact(lecture_id: str, db: Session = Depends(get_db)):
    """Get PDF artifact metadata and download URL for a lecture."""
    lecture = db.query(Lecture).filter(Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")

    artifact = (
        db.query(Artifact)
        .filter(Artifact.lecture_id == lecture_id, Artifact.type == "pdf")
        .order_by(Artifact.created_at.desc())
        .first()
    )
    if not artifact:
        raise HTTPException(status_code=404, detail="PDF not yet available")

    storage = StorageService()
    download_url = storage.get_download_url(artifact.storage_key)

    return {
        "artifact_id": str(artifact.id),
        "type": artifact.type,
        "mime_type": artifact.mime_type,
        "size_bytes": artifact.size_bytes,
        "download_url": download_url,
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
    }
