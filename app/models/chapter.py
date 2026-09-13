import uuid
from sqlalchemy import Column, String, Text, Integer, DateTime, func, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class LectureChapter(Base):
    __tablename__ = "lecture_chapters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lecture_id = Column(UUID(as_uuid=True), ForeignKey("lectures.id"), nullable=False)
    
    chapter_index = Column(Integer, nullable=False)
    title = Column(Text, nullable=False)
    start_seconds = Column(Numeric, nullable=False)
    end_seconds = Column(Numeric, nullable=False)
    source = Column(String, nullable=False) # 'youtube' or 'derived'
    
    lecture = relationship("Lecture", back_populates="chapters")

    __table_args__ = (
        UniqueConstraint("lecture_id", "chapter_index", name="uix_lecture_chapter"),
    )
