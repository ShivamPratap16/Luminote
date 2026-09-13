"""Tests for structured notes schema validation."""
import pytest
from pydantic import ValidationError
from app.schemas.notes import StructuredNotes, NoteSection


class TestStructuredNotesValidation:
    """Validate that the StructuredNotes schema rejects bad AI output."""

    def test_valid_notes(self):
        data = {
            "title": "Test Lecture",
            "overview": "This is a test lecture about testing.",
            "sections": [
                {
                    "title": "Introduction",
                    "summary": "The lecture begins with an introduction.",
                    "key_points": ["Testing is important"],
                    "examples": ["Example 1"],
                    "important_terms": ["unit test"],
                    "timestamps": [0.0, 10.5],
                }
            ],
            "final_takeaways": ["Testing matters"],
        }
        notes = StructuredNotes.model_validate(data)
        assert notes.title == "Test Lecture"
        assert len(notes.sections) == 1
        assert notes.sections[0].key_points == ["Testing is important"]

    def test_missing_title_raises(self):
        with pytest.raises(ValidationError):
            StructuredNotes.model_validate({
                "overview": "Overview",
                "sections": [{"title": "S", "summary": "S"}],
            })

    def test_empty_title_raises(self):
        with pytest.raises(ValidationError):
            StructuredNotes.model_validate({
                "title": "",
                "overview": "Overview",
                "sections": [{"title": "S", "summary": "S"}],
            })

    def test_missing_overview_raises(self):
        with pytest.raises(ValidationError):
            StructuredNotes.model_validate({
                "title": "Title",
                "sections": [{"title": "S", "summary": "S"}],
            })

    def test_empty_sections_raises(self):
        with pytest.raises(ValidationError):
            StructuredNotes.model_validate({
                "title": "Title",
                "overview": "Overview",
                "sections": [],
            })

    def test_section_missing_summary_raises(self):
        with pytest.raises(ValidationError):
            StructuredNotes.model_validate({
                "title": "Title",
                "overview": "Overview",
                "sections": [{"title": "Section"}],
            })

    def test_optional_fields_default(self):
        notes = StructuredNotes.model_validate({
            "title": "Title",
            "overview": "Overview",
            "sections": [{"title": "S", "summary": "Summary"}],
        })
        assert notes.final_takeaways == []
        assert notes.sections[0].examples == []
        assert notes.sections[0].important_terms == []
        assert notes.sections[0].timestamps == []

    def test_rejects_non_json(self):
        with pytest.raises(ValidationError):
            StructuredNotes.model_validate("not json")

    def test_multiple_sections(self):
        data = {
            "title": "Multi-section",
            "overview": "A lecture with several parts.",
            "sections": [
                {"title": f"Section {i}", "summary": f"Summary {i}"}
                for i in range(5)
            ],
        }
        notes = StructuredNotes.model_validate(data)
        assert len(notes.sections) == 5
