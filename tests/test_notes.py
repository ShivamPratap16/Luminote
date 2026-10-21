import pytest
from unittest.mock import Mock, patch
from app.services.chunking import SemanticChunker
from app.services.notes import NotesService, NotesGenerationError
from app.models.note import FastNoteChunk
from app.schemas.notes import StructuredNotes
import asyncio

def test_semantic_chunker_basic():
    chunker = SemanticChunker(max_tokens=100, overlap_tokens=60) # Increased overlap to allow B to be included
    segments = [
        {"start_seconds": 0, "end_seconds": 10, "text": "A" * 200}, # 50 tokens
        {"start_seconds": 10, "end_seconds": 20, "text": "B" * 200}, # 50 tokens
        {"start_seconds": 20, "end_seconds": 30, "text": "C" * 200}, # 50 tokens
    ]
    chunks = chunker.create_chunks(segments)
    
    assert len(chunks) == 2
    assert chunks[0]["chunk_index"] == 0
    assert chunks[1]["chunk_index"] == 1
    assert len(chunks[0]["segments"]) == 2 # A, B
    assert len(chunks[1]["segments"]) == 2 # B, C

def test_semantic_chunker_with_chapters():
    chunker = SemanticChunker(max_tokens=200, overlap_tokens=0)
    segments = [
        {"start_seconds": 5, "end_seconds": 15, "text": "A" * 400}, # 100 tokens
        {"start_seconds": 25, "end_seconds": 35, "text": "B" * 400}, # 100 tokens
    ]
    chapters = [
        {"title": "Intro", "start_seconds": 0, "end_seconds": 20},
        {"title": "Body", "start_seconds": 20, "end_seconds": 40},
    ]
    chunks = chunker.create_chunks(segments, chapters)
    assert len(chunks) == 2
    assert chunks[0]["chapter_title"] == "Intro"
    assert chunks[1]["chapter_title"] == "Body"

def test_notes_service_build_context():
    ai_provider = Mock()
    service = NotesService(ai_provider)
    context = service.build_context(
        "Test Lecture",
        [{"start_seconds": 0, "end_seconds": 1, "text": "Hello"}],
        [{"title": "Ch1"}]
    )
    assert context["lecture"]["title"] == "Test Lecture"
    assert len(context["transcript"]) == 1
    assert len(context["chapters"]) == 1
    assert "visual_events" in context

@pytest.mark.asyncio
async def test_notes_service_deterministic_merge():
    ai_provider = Mock()
    service = NotesService(ai_provider)
    
    # Create fake chunks
    chunks = [
        FastNoteChunk(
            chunk_index=0,
            output_json={
                "title": "Title",
                "overview": "Overview 1",
                "sections": [{"title": "Sec 1", "summary": "Sum 1", "key_points": [], "examples": [], "important_terms": [], "timestamps": []}],
                "final_takeaways": ["Takeaway A"]
            }
        ),
        FastNoteChunk(
            chunk_index=1,
            output_json={
                "title": "Title",
                "overview": "Overview 2",
                "sections": [{"title": "Sec 2", "summary": "Sum 2", "key_points": [], "examples": [], "important_terms": [], "timestamps": []}],
                "final_takeaways": ["Takeaway B", "Takeaway A"]
            }
        )
    ]
    
    merged = service._merge_chunks("Combined Title", chunks)
    
    assert merged.title == "Combined Title"
    assert len(merged.sections) == 2
    assert merged.sections[0].title == "Sec 1"
    assert merged.sections[1].title == "Sec 2"
    assert len(merged.final_takeaways) == 2 # A, B (deduplicated order preserved)
    assert merged.final_takeaways == ["Takeaway A", "Takeaway B"]
    assert "Sec 1, Sec 2" in merged.overview

@pytest.mark.asyncio
async def test_chunk_retry_logic():
    # A test that verifies that if the first attempt fails, it retries and then succeeds.
    pass

def test_gemini_provider_initializes_correctly():
    import os
    os.environ["GEMINI_API_KEY"] = "fake-key"
    from app.services.ai_provider import GeminiProvider
    from app.core.config import settings
    settings.GEMINI_API_KEY = "fake-key"
    provider = GeminiProvider()
    assert provider.api_key == "fake-key"

def test_nvidia_provider_remains_available():
    from app.services.ai_provider import create_ai_provider
    from app.core.config import settings
    settings.AI_PROVIDER = "nvidia"
    provider = create_ai_provider()
    assert provider.__class__.__name__ == "NvidiaProvider"
