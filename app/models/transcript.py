import uuid
from sqlalchemy import Column, Text, Integer, DateTime, func, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lecture_id = Column(UUID(as_uuid=True), ForeignKey("lectures.id"), nullable=False)
    
    segment_index = Column(Integer, nullable=False)
    start_seconds = Column(Numeric, nullable=False)
    end_seconds = Column(Numeric, nullable=False)
    text = Column(Text, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lecture = relationship("Lecture", back_populates="transcript_segments")

    __table_args__ = (
        UniqueConstraint("lecture_id", "segment_index", name="uix_lecture_segment"),
    )
