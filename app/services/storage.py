"""Storage service abstraction.

Provides a uniform interface for storing and retrieving artifacts.
V1 uses local filesystem. Future versions swap in S3-compatible storage
without changing callers.
"""
import os
import shutil
import uuid
import hashlib
import structlog
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from app.core.config import settings

logger = structlog.get_logger(__name__)


@dataclass
class StoredFile:
    """Result of storing a file."""
    storage_key: str
    size_bytes: int
    checksum: str


class StorageError(Exception):
    """Raised when storage operations fail."""
    pass


class StorageBackend(ABC):
    """Abstract storage backend."""

    @abstractmethod
    def store(self, local_path: str, key: str) -> StoredFile:
        """Store a local file under the given key."""
        ...

    @abstractmethod
    def get_url(self, key: str) -> str:
        """Return a URL or path to access the stored file."""
        ...

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if a key exists in storage."""
        ...


class LocalStorageBackend(StorageBackend):
    """Local filesystem storage for development."""

    def __init__(self, base_path: str | None = None):
        self.base_path = base_path or settings.STORAGE_LOCAL_PATH
        os.makedirs(self.base_path, exist_ok=True)

    def store(self, local_path: str, key: str) -> StoredFile:
        dest = os.path.join(self.base_path, key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        shutil.copy2(local_path, dest)

        size = os.path.getsize(dest)
        checksum = self._compute_checksum(dest)

        logger.info("File stored locally", key=key, size_bytes=size)
        return StoredFile(storage_key=key, size_bytes=size, checksum=checksum)

    def get_url(self, key: str) -> str:
        return os.path.join(self.base_path, key)

    def exists(self, key: str) -> bool:
        return os.path.exists(os.path.join(self.base_path, key))

    @staticmethod
    def _compute_checksum(path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()


class StorageService:
    """Application-level storage service."""

    def __init__(self, backend: StorageBackend | None = None):
        if backend:
            self.backend = backend
        elif settings.STORAGE_BACKEND == "local":
            self.backend = LocalStorageBackend()
        else:
            # Future: S3Backend
            self.backend = LocalStorageBackend()

    def store_artifact(
        self,
        local_path: str,
        lecture_id: str,
        artifact_type: str,
        extension: str = "pdf",
    ) -> StoredFile:
        """Store an artifact file with a deterministic key structure."""
        key = f"lectures/{lecture_id}/{artifact_type}/{uuid.uuid4().hex}.{extension}"
        return self.backend.store(local_path, key)

    def get_download_url(self, storage_key: str) -> str:
        """Get a download URL for a stored artifact."""
        return self.backend.get_url(storage_key)
