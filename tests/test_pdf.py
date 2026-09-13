"""Tests for PDF generation service."""
import os
import pytest
from app.schemas.notes import StructuredNotes
from app.services.pdf import PdfService, format_timestamp


SAMPLE_NOTES = StructuredNotes.model_validate({
    "title": "Test Lecture: Virtual Memory",
    "overview": "This lecture covers the fundamentals of virtual memory in operating systems.",
    "sections": [
        {
            "title": "What is Virtual Memory?",
            "summary": "Virtual memory is a memory management technique.",
            "key_points": [
                "Virtual memory provides address space isolation",
                "Pages are mapped to physical frames",
            ],
            "examples": ["Page table example"],
            "important_terms": ["page table", "TLB", "page fault"],
            "timestamps": [120.0, 245.5],
        },
        {
            "title": "Page Replacement",
            "summary": "When memory is full, pages must be evicted.",
            "key_points": ["LRU algorithm", "Clock algorithm"],
            "examples": [],
            "important_terms": ["LRU", "FIFO"],
            "timestamps": [600.0],
        },
    ],
    "final_takeaways": [
        "Virtual memory is essential for modern OS",
        "Page replacement algorithms trade off complexity for performance",
    ],
})


class TestFormatTimestamp:
    def test_seconds_only(self):
        assert format_timestamp(45) == "0:45"

    def test_minutes_and_seconds(self):
        assert format_timestamp(125) == "2:05"

    def test_hours(self):
        assert format_timestamp(3661) == "1:01:01"

    def test_zero(self):
        assert format_timestamp(0) == "0:00"


class TestPdfServiceHtmlRendering:
    def test_render_html(self):
        service = PdfService()
        html = service.render_html(SAMPLE_NOTES, source_url="https://youtube.com/watch?v=test")
        assert "Virtual Memory" in html
        assert "Page Replacement" in html
        assert "page table" in html
        assert "youtube.com" in html

    def test_render_html_without_source_url(self):
        service = PdfService()
        html = service.render_html(SAMPLE_NOTES)
        assert "Virtual Memory" in html


class TestPdfServiceGeneration:
    """PDF generation requires Playwright + Chromium.
    These tests are skipped if Playwright is not installed."""

    @pytest.fixture
    def can_use_playwright(self):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                browser.close()
            return True
        except Exception:
            pytest.skip("Playwright/Chromium not available")

    def test_generate_pdf(self, can_use_playwright, tmp_path):
        service = PdfService()
        pdf_path = service.generate_pdf(SAMPLE_NOTES, output_dir=str(tmp_path))
        assert os.path.exists(pdf_path)
        assert os.path.getsize(pdf_path) > 0
        assert pdf_path.endswith(".pdf")
