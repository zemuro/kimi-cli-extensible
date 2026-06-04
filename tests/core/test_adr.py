"""Tests for ADR render and parse."""

from __future__ import annotations

import pytest

from consilium.plan.adr import ADR, parse_adr, render_adr


class TestRenderAdr:
    def test_renders_basic_adr(self) -> None:
        adr = ADR(
            adr_id="001",
            title="Use PostgreSQL",
            status="accepted",
            context="SQLite has concurrency issues.",
            decision="Use PostgreSQL.",
            consequences=["Better concurrency", "More complex backups"],
        )
        text = render_adr(adr)
        assert "ADR 001: Use PostgreSQL" in text
        assert "status: accepted" in text
        assert "SQLite has concurrency issues." in text
        assert "Use PostgreSQL." in text
        assert "- Better concurrency" in text

    def test_renders_date(self) -> None:
        adr = ADR(adr_id="002", title="Test", date=1716854400.0)
        text = render_adr(adr)
        assert "date: 2024-05-28" in text

    def test_renders_supersedes(self) -> None:
        adr = ADR(adr_id="003", title="Test", supersedes="001")
        text = render_adr(adr)
        assert 'supersedes: "001"' in text


class TestParseAdr:
    def test_parses_basic_adr(self) -> None:
        text = render_adr(
            ADR(
                adr_id="001",
                title="Use PostgreSQL",
                status="accepted",
                context="SQLite has issues.",
                decision="Use PostgreSQL.",
                consequences=["Better concurrency"],
            )
        )
        adr = parse_adr(text)
        assert adr.adr_id == "001"
        assert adr.title == "Use PostgreSQL"
        assert adr.status == "accepted"
        assert adr.context == "SQLite has issues."
        assert adr.decision == "Use PostgreSQL."
        assert adr.consequences == ["Better concurrency"]

    def test_parses_date(self) -> None:
        text = render_adr(ADR(adr_id="002", title="Test", date=1716854400.0))
        adr = parse_adr(text)
        assert adr.date == pytest.approx(1716854400.0)

    def test_roundtrip(self) -> None:
        original = ADR(
            adr_id="005",
            title="Roundtrip",
            status="proposed",
            date=1716854400.0,
            supersedes="004",
            superseded_by="006",
            context="Context here.",
            decision="Decide this.",
            consequences=["Consequence A", "Consequence B"],
        )
        text = render_adr(original)
        parsed = parse_adr(text)
        assert parsed.adr_id == original.adr_id
        assert parsed.title == original.title
        assert parsed.status == original.status
        assert parsed.date == pytest.approx(original.date)  # type: ignore[union-attr]
        assert parsed.supersedes == original.supersedes
        assert parsed.superseded_by == original.superseded_by
        assert parsed.context == original.context
        assert parsed.decision == original.decision
        assert parsed.consequences == original.consequences

    def test_missing_frontmatter_raises(self) -> None:
        from consilium.plan.parser import PlanParseError

        with pytest.raises(PlanParseError):
            parse_adr("# No frontmatter\n")
