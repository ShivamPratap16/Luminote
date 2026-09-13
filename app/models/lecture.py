import uuid
from sqlalchemy import Column, String, Text, Integer, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class Lecture(Base):
    __tablename__ = "lectures"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    youtube_video_id = Column(String, unique=True, index=True, nullable=False)
    youtube_url = Column(Text, nullable=False)
    title = Column(Text, nullable=True)
    channel_name = Column(Text, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    thumbnail_url = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="pending")
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    jobs = relationship("ProcessingJob", back_populates="lecture")
    transcript_segments = relationship("TranscriptSegment", back_populates="lecture")
    chapters = relationship("LectureChapter", back_populates="lecture")
    notes = relationship("Note", back_populates="lecture")
    artifacts = relationship("Artifact", back_populates="lecture")
