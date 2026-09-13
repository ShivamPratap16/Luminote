from pydantic import BaseModel
from typing import Optional
from uuid import UUID

class JobResponse(BaseModel):
    id: UUID
    lecture_id: UUID
    status: str
    current_stage: str
    progress: float
    attempt: int
    error: Optional[str] = None

    class Config:
        from_attributes = True
