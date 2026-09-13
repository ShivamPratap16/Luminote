from pydantic import BaseModel, HttpUrl
from typing import Optional
from uuid import UUID
from datetime import datetime

class LectureCreate(BaseModel):
    youtube_url: HttpUrl

class LectureResponse(BaseModel):
    id: UUID
    youtube_video_id: str
    title: Optional[str] = None
    duration_seconds: Optional[int] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

class LectureCreateResponse(BaseModel):
    lecture_id: UUID
    job_id: UUID
    status: str
