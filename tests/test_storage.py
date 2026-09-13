"""Tests for StorageService."""
import os
import tempfile
import pytest
from app.services.storage import StorageService, LocalStorageBackend


class TestLocalStorageBackend:
    def test_store_and_retrieve(self, tmp_path):
        backend = LocalStorageBackend(base_path=str(tmp_path))

        # Create a temp file to store
        src = tmp_path / "source.txt"
        src.write_text("hello world")

        result = backend.store(str(src), "test/file.txt")
        assert result.storage_key == "test/file.txt"
        assert result.size_bytes == 11
        assert len(result.checksum) == 64  # SHA-256 hex

        assert backend.exists("test/file.txt")
        assert not backend.exists("nonexistent.txt")

    def test_get_url(self, tmp_path):
        backend = LocalStorageBackend(base_path=str(tmp_path))
        url = backend.get_url("lectures/abc/pdf/notes.pdf")
        assert "lectures" in url
        assert "notes.pdf" in url


class TestStorageService:
    def test_store_artifact(self, tmp_path):
        backend = LocalStorageBackend(base_path=str(tmp_path))
        svc = StorageService(backend=backend)

        # Create a temp file
        src = tmp_path / "test.pdf"
        src.write_bytes(b"%PDF-1.4 fake pdf content")

        result = svc.store_artifact(
            local_path=str(src),
            lecture_id="lecture-123",
            artifact_type="pdf",
        )
        assert result.storage_key.startswith("lectures/lecture-123/pdf/")
        assert result.storage_key.endswith(".pdf")
        assert result.size_bytes > 0
