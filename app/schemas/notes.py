"""Pydantic schemas for validating structured notes produced by AI.

This is the schema contract between the AI provider output and the database.
The AI must produce JSON matching these models; malformed output is rejected.
"""
from pydantic import BaseModel, Field
from typing import List, Optional


class NoteSection(BaseModel):
    """A single section within structured notes."""
    title: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    key_points: List[str] = Field(default_factory=list)
    examples: List[str] = Field(default_factory=list)
    important_terms: List[str] = Field(default_factory=list)
    timestamps: List[float] = Field(default_factory=list)


class StructuredNotes(BaseModel):
    """Root schema for structured notes. Versioned for future evolution."""
    title: str = Field(..., min_length=1)
    overview: str = Field(..., min_length=1)
    sections: List[NoteSection] = Field(..., min_length=1)
    final_takeaways: List[str] = Field(default_factory=list)


class NotesResponse(BaseModel):
    """API response schema for notes endpoint."""
    lecture_id: str
    version: int
    schema_version: str
    content: StructuredNotes

    class Config:
        from_attributes = True
