import uuid
from sqlalchemy import Column, String, Text, Numeric, DateTime, func, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class VisualEvent(Base):
    __tablename__ = 'visual_events'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lecture_id = Column(UUID(as_uuid=True), ForeignKey('lectures.id'), nullable=False)
    
    timestamp = Column(Numeric, nullable=False)
    frame_hash = Column(String, nullable=False)
    
    event_type = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    visible_text = Column(JSONB, nullable=False)
    key_information = Column(JSONB, nullable=False)
    
    frame_storage_key = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lecture = relationship('Lecture', back_populates='visual_events')

    __table_args__ = (
        UniqueConstraint('lecture_id', 'timestamp', 'frame_hash', name='uix_visual_event_identity'),
    )
