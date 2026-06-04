"""Tests for blob_store."""

from __future__ import annotations

from consilium.do.blob_store import exists, retrieve, retrieve_text, store


def test_blob_store_roundtrip() -> None:
    content = "hello world"
    content_hash = store(content)
    assert content_hash is not None
    assert len(content_hash) == 64  # SHA256 hex

    retrieved = retrieve_text(content_hash)
    assert retrieved == content


def test_blob_store_bytes_roundtrip() -> None:
    content = b"\x00\x01\x02\x03"
    content_hash = store(content)
    retrieved = retrieve(content_hash)
    assert retrieved == content


def test_blob_store_deduplication() -> None:
    content = "dedup test"
    h1 = store(content)
    h2 = store(content)
    assert h1 == h2


def test_blob_store_missing() -> None:
    assert retrieve("nonexistent") is None
    assert retrieve_text("nonexistent") is None
    assert exists("nonexistent") is False
