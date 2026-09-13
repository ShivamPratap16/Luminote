import uuid
from sqlalchemy import Column, String, Text, DateTime, func, ForeignKey, BigInteger, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lecture_id = Column(UUID(as_uuid=True), ForeignKey("lectures.id"), nullable=False)
    note_id = Column(UUID(as_uuid=True), ForeignKey("notes.id"), nullable=True)
    
    type = Column(String, nullable=False)
    storage_key = Column(Text, nullable=False)
    mime_type = Column(String, nullable=False)
    size_bytes = Column(BigInteger, nullable=True)
    checksum = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lecture = relationship("Lecture", back_populates="artifacts")
    note = relationship("Note", back_populates="artifacts")

    __table_args__ = (
        UniqueConstraint("lecture_id", "note_id", "type", name="uix_lecture_note_type"),
    )
