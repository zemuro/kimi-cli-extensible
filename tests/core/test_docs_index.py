"""Tests for documentation index parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from consilium.plan.docs_index import (
    generate_docs_index,
    parse_docs_index,
    read_docs_index_cache,
    write_docs_index_cache,
)
from consilium.plan.models import DocStatus, UpdatePolicy


README_SAMPLE = """\
# Project Documentation

## Active Documents

| Document | Purpose | Status | Updated | Policy | Related Phases |
|----------|---------|--------|---------|--------|----------------|
| architecture.md | System design | current | 2026-05-20 | think_and_do | 1-3 |
| decisions.md | ADRs | current | 2026-05-22 | append_only | all |
| guidelines.md | Patterns | current | 2026-05-23 | think_and_do | all |
| findings.md | Research | current | 2026-05-24 | append_only | 4-12 |
| old_arch.md | Old design | stale | 2026-04-15 | think_only | 1-2 |

## Stale Documents

| Document | Reason | Superseded By |
|----------|--------|---------------|
| old_arch.md | Outdated | findings.md |
"""


class TestParseDocsIndex:
    def test_parses_active_documents(self) -> None:
        index = parse_docs_index(README_SAMPLE)
        assert len(index.documents) == 5

    def test_document_details(self) -> None:
        index = parse_docs_index(README_SAMPLE)
        arch = index.documents[0]
        assert arch.path == "architecture.md"
        assert arch.purpose == "System design"
        assert arch.status == DocStatus.CURRENT
        assert arch.last_updated is not None
        assert arch.update_policy == UpdatePolicy.THINK_AND_DO
        assert arch.related_phases == ["phase-1", "phase-2", "phase-3"]

    def test_stale_document(self) -> None:
        index = parse_docs_index(README_SAMPLE)
        old = index.documents[4]
        assert old.path == "old_arch.md"
        assert old.status == DocStatus.STALE
        assert old.update_policy == UpdatePolicy.THINK_ONLY
        assert old.related_phases == ["phase-1", "phase-2"]

    def test_get_relevant_docs(self) -> None:
        index = parse_docs_index(README_SAMPLE)
        relevant = index.get_relevant_docs("phase-2")
        paths = [d.path for d in relevant]
        assert "architecture.md" in paths
        assert "old_arch.md" in paths

    def test_get_current_docs(self) -> None:
        index = parse_docs_index(README_SAMPLE)
        current = index.get_current_docs()
        assert len(current) == 4
        assert all(d.status == DocStatus.CURRENT for d in current)

    def test_all_related_phases(self) -> None:
        index = parse_docs_index(README_SAMPLE)
        decisions = index.documents[1]
        assert decisions.related_phases == []


class TestDocsIndexCache:
    def test_roundtrip(self, tmp_path: Path) -> None:
        index = parse_docs_index(README_SAMPLE)
        cache_path = tmp_path / ".consilium" / "docs_index.json"
        write_docs_index_cache(index, cache_path)
        assert cache_path.exists()

        loaded = read_docs_index_cache(cache_path)
        assert len(loaded.documents) == 5
        assert loaded.documents[0].path == "architecture.md"

    def test_missing_cache_returns_empty(self, tmp_path: Path) -> None:
        cache_path = tmp_path / ".consilium" / "docs_index.json"
        loaded = read_docs_index_cache(cache_path)
        assert loaded.documents == []

    def test_generate_from_file(self, tmp_path: Path) -> None:
        readme = tmp_path / "docs" / "README.md"
        readme.parent.mkdir(parents=True, exist_ok=True)
        readme.write_text(README_SAMPLE, encoding="utf-8")
        index = generate_docs_index(readme)
        assert len(index.documents) == 5
