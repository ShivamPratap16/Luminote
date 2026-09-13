from pydantic import BaseModel, Field
from typing import List

class VisualEventSchema(BaseModel):
    event_type: str = Field(..., description="Type of visual event (e.g., slide, diagram, formula, code, table, chart, example, other)")
    description: str = Field(..., description="Detailed educational description of what is shown")
    visible_text: List[str] = Field(default_factory=list, description="Important readable text in the frame")
    key_information: List[str] = Field(default_factory=list, description="Key concepts or relationships shown")

class VisionResponseSchema(BaseModel):
    visual_events: List[VisualEventSchema] = Field(default_factory=list)
