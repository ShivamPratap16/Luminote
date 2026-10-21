"""Transcript segmentation and chunking service.

Divides the lecture transcript into semantic chunks for parallel AI processing.
Prioritizes YouTube/Lecture chapters if available. Falls back to token-aware
splitting with overlap to preserve continuity.
"""
import hashlib
from typing import Any, Dict, List
import structlog
from app.core.config import settings

logger = structlog.get_logger(__name__)


def approximate_tokens(text: str) -> int:
    """Rough approximation of token count.
    
    A standard rule of thumb is 1 token ~= 4 characters in English.
    """
    return len(text) // 4


class SemanticChunker:
    """Service to create semantic chunks from a transcript."""

    def __init__(
        self,
        max_tokens: int = settings.FAST_NOTES_CHUNK_MAX_TOKENS,
        overlap_tokens: int = settings.FAST_NOTES_CHUNK_OVERLAP_TOKENS,
    ):
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens

    def create_chunks(
        self,
        transcript_segments: List[Dict[str, Any]],
        chapters: List[Dict[str, Any]] | None = None,
    ) -> List[Dict[str, Any]]:
        """Create semantic chunks from transcript segments.

        Returns a list of chunks. Each chunk is a dictionary:
        {
            "chunk_index": int,
            "chapter_title": str | None,
            "segments": List[Dict[str, Any]],
            "content_hash": str,
        }
        """
        if not transcript_segments:
            return []

        chunks = []
        current_chunk_segments = []
        current_tokens = 0
        chunk_index = 0
        current_chapter = None
        
        # If chapters exist, use them to guide segmentation
        # For simplicity, we just use the token limit and keep track of chapters
        
        # Sort segments by start_seconds
        sorted_segments = sorted(transcript_segments, key=lambda x: x.get("start_seconds", 0))

        def _get_current_chapter(time_sec: float) -> str | None:
            if not chapters:
                return None
            for ch in chapters:
                if ch.get("start_seconds", 0) <= time_sec <= ch.get("end_seconds", 999999):
                    return ch.get("title")
            return None

        # Build chunks
        for seg in sorted_segments:
            text = seg.get("text", "")
            tokens = approximate_tokens(text)
            
            # Check if this segment crosses a chapter boundary
            seg_start = seg.get("start_seconds", 0)
            seg_chapter = _get_current_chapter(seg_start)
            
            chapter_changed = False
            if seg_chapter and current_chapter and seg_chapter != current_chapter:
                chapter_changed = True

            # If token limit reached OR chapter explicitly changed (and we have enough tokens to justify splitting)
            # Actually, to avoid tiny chunks, we only split on chapter if current tokens > (max_tokens / 4)
            force_split = chapter_changed and current_tokens > (self.max_tokens // 4)
            
            if current_tokens + tokens > self.max_tokens or force_split:
                # Finalize current chunk
                if current_chunk_segments:
                    chunks.append(self._finalize_chunk(chunk_index, current_chapter, current_chunk_segments))
                    chunk_index += 1
                
                # Start new chunk with overlap
                overlap_segments = []
                overlap_tokens = 0
                for prev_seg in reversed(current_chunk_segments):
                    prev_tokens = approximate_tokens(prev_seg.get("text", ""))
                    if overlap_tokens + prev_tokens > self.overlap_tokens:
                        break
                    overlap_segments.insert(0, prev_seg)
                    overlap_tokens += prev_tokens
                
                current_chunk_segments = list(overlap_segments)
                current_tokens = overlap_tokens
                
                if chapter_changed:
                    current_chapter = seg_chapter

            if not current_chapter:
                current_chapter = seg_chapter

            current_chunk_segments.append(seg)
            current_tokens += tokens

        # Finalize the last chunk
        if current_chunk_segments:
            chunks.append(self._finalize_chunk(chunk_index, current_chapter, current_chunk_segments))

        return chunks

    def _finalize_chunk(self, index: int, chapter_title: str | None, segments: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create the final chunk object."""
        combined_text = " ".join(s.get("text", "") for s in segments)
        content_hash = hashlib.md5(combined_text.encode('utf-8')).hexdigest()
        
        return {
            "chunk_index": index,
            "chapter_title": chapter_title,
            "segments": segments,
            "content_hash": content_hash,
            "start_time": segments[0].get("start_seconds", 0) if segments else 0,
            "end_time": segments[-1].get("end_seconds", 0) if segments else 0,
        }
