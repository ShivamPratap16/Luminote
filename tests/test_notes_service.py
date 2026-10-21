"""Tests for NotesService context assembly and AI output validation."""
import pytest
from unittest.mock import MagicMock
from pydantic import ValidationError

from app.services.notes import NotesService, NotesGenerationError
from app.services.ai_provider import AIProvider, AIProviderInvalidResponse


class FakeAIProvider(AIProvider):
    """Test double for AIProvider that returns configurable responses."""

    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.call_count = 0

    def generate_structured_notes(self, context):
        self.call_count += 1
        if self._error:
            raise self._error
        return self._response, {"input_tokens": 0, "output_tokens": 0}


VALID_NOTES = {
    "title": "Test Lecture",
    "overview": "This is a test overview.",
    "sections": [
        {
            "title": "Section One",
            "summary": "Summary of section one.",
            "key_points": ["Point A"],
            "examples": [],
            "important_terms": ["term1"],
            "timestamps": [12.5],
        }
    ],
    "final_takeaways": ["Important takeaway"],
}


class TestContextAssembly:
    def test_basic_context(self):
        svc = NotesService(FakeAIProvider(response=VALID_NOTES))
        transcript = [
            {"start_seconds": 0, "end_seconds": 5, "text": "Hello world"},
            {"start_seconds": 5, "end_seconds": 10, "text": "More text"},
        ]
        context = svc.build_context("Test", transcript, [])
        assert context["lecture"]["title"] == "Test"
        assert len(context["transcript"]) == 2

    def test_context_with_chapters(self):
        svc = NotesService(FakeAIProvider(response=VALID_NOTES))
        chapters = [{"title": "Ch1", "start_seconds": 0, "end_seconds": 60}]
        context = svc.build_context("Test", [], chapters)
        assert len(context["chapters"]) == 1

    def test_context_truncation(self):
        svc = NotesService(FakeAIProvider(response=VALID_NOTES))
        # Create transcript exceeding MAX_TRANSCRIPT_CHARS
        long_text = "x" * 60_000
        transcript = [
            {"start_seconds": 0, "end_seconds": 5, "text": long_text},
            {"start_seconds": 5, "end_seconds": 10, "text": long_text},
        ]
        context = svc.build_context("Test", transcript)
        # Should have truncated before including all segments
        last_text = context["transcript"][-1]["text"]
        assert "TRUNCATED" in last_text


class TestGenerateNotes:
    def test_valid_generation(self):
        provider = FakeAIProvider(response=VALID_NOTES)
        svc = NotesService(provider)
        result = svc.generate_notes("Title", [{"start_seconds": 0, "end_seconds": 5, "text": "Hi"}])
        assert result.title == "Test Lecture"
        assert provider.call_count == 1

    def test_invalid_json_retries(self):
        """If AI returns invalid JSON, the service should retry."""
        provider = FakeAIProvider(error=AIProviderInvalidResponse("bad json"))
        svc = NotesService(provider)
        with pytest.raises(NotesGenerationError):
            svc.generate_notes("Title", [{"start_seconds": 0, "end_seconds": 5, "text": "Hi"}])
        assert provider.call_count == 2  # default max_retries=2

    def test_invalid_schema_retries(self):
        """If AI returns valid JSON but wrong schema, the service should retry."""
        bad_notes = {"title": "ok", "overview": "ok", "sections": []}  # empty sections
        provider = FakeAIProvider(response=bad_notes)
        svc = NotesService(provider)
        with pytest.raises(NotesGenerationError):
            svc.generate_notes("Title", [{"start_seconds": 0, "end_seconds": 5, "text": "Hi"}])
        assert provider.call_count == 2
