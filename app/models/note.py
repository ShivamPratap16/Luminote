import uuid
from sqlalchemy import Column, String, Integer, DateTime, func, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class Note(Base):
    __tablename__ = "notes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lecture_id = Column(UUID(as_uuid=True), ForeignKey("lectures.id"), nullable=False)
    
    version = Column(Integer, nullable=False)
    schema_version = Column(String, nullable=False)
    content_json = Column(JSONB, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    lecture = relationship("Lecture", back_populates="notes")
    artifacts = relationship("Artifact", back_populates="note")

    __table_args__ = (
        UniqueConstraint("lecture_id", "version", name="uix_lecture_note_version"),
    )


class FastNoteChunk(Base):
    """Stores incrementally generated fast notes chunks to enable idempotency/retries."""
    __tablename__ = "fast_note_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lecture_id = Column(UUID(as_uuid=True), ForeignKey("lectures.id"), nullable=False, index=True)
    
    pipeline_version = Column(String, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content_hash = Column(String, nullable=False)  # Hash of the chunk's transcript text
    
    status = Column(String, nullable=False, default="pending")  # pending, processing, completed, failed
    attempt_count = Column(Integer, default=0)
    output_json = Column(JSONB, nullable=True)
    error_message = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("lecture_id", "pipeline_version", "chunk_index", name="uix_lecture_chunk"),
    )
