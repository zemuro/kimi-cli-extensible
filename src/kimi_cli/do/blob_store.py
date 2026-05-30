"""Content-addressed blob store for file snapshots.

Layout:
    ~/.kimi/blobs/
    ├── ab/
    │   └── cdef1234...  (full sha256 filename)
    └── 12/
        └── 3456abcd...  (full sha256 filename)

Storage format: raw file bytes, no compression.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

BLOB_DIR = Path.home() / ".kimi" / "blobs"


def _blob_path(content_hash: str) -> Path:
    prefix = content_hash[:2]
    return BLOB_DIR / prefix / content_hash


def store(content: bytes | str) -> str:
    """Store content and return its SHA256 hash."""
    if isinstance(content, str):
        content = content.encode("utf-8")

    content_hash = hashlib.sha256(content).hexdigest()
    path = _blob_path(content_hash)

    if path.exists():
        return content_hash  # deduplication

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content_hash


def retrieve(content_hash: str) -> bytes | None:
    """Retrieve content by hash. Returns None if not found."""
    path = _blob_path(content_hash)
    if not path.exists():
        return None
    return path.read_bytes()


def retrieve_text(content_hash: str) -> str | None:
    """Retrieve content as UTF-8 text."""
    data = retrieve(content_hash)
    return data.decode("utf-8") if data is not None else None


def exists(content_hash: str) -> bool:
    return _blob_path(content_hash).exists()
