"""Tests for Finding render and parse."""

from __future__ import annotations

import pytest

from consilium.plan.finding import Finding, parse_finding, render_finding


class TestRenderFinding:
    def test_renders_basic_finding(self) -> None:
        finding = Finding(
            finding_id="001",
            title="Auth Comparison",
            summary="JWT+JWE is required.",
            evidence=["RFC 7516"],
            impact="Affects Phase 3.",
        )
        text = render_finding(finding)
        assert "Finding 001: Auth Comparison" in text
        assert 'finding_id: "001"' in text
        assert "JWT+JWE is required." in text
        assert "- RFC 7516" in text
        assert "Affects Phase 3." in text

    def test_renders_related_phases(self) -> None:
        finding = Finding(
            finding_id="002",
            title="Test",
            related_phases=["phase-01", "phase-02"],
        )
        text = render_finding(finding)
        assert "related_phases:" in text
        assert "  - phase-01" in text
        assert "  - phase-02" in text


class TestParseFinding:
    def test_parses_basic_finding(self) -> None:
        text = render_finding(
            Finding(
                finding_id="001",
                title="Auth Comparison",
                summary="JWT+JWE required.",
                evidence=["RFC 7516"],
                impact="Affects Phase 3.",
            )
        )
        finding = parse_finding(text)
        assert finding.finding_id == "001"
        assert finding.title == "Auth Comparison"
        assert finding.summary == "JWT+JWE required."
        assert finding.evidence == ["RFC 7516"]
        assert finding.impact == "Affects Phase 3."

    def test_roundtrip(self) -> None:
        original = Finding(
            finding_id="003",
            title="Roundtrip",
            date=1716854400.0,
            related_phases=["phase-03"],
            summary="Summary.",
            evidence=["Evidence A"],
            impact="Impact.",
        )
        text = render_finding(original)
        parsed = parse_finding(text)
        assert parsed.finding_id == original.finding_id
        assert parsed.title == original.title
        assert parsed.date == pytest.approx(original.date)  # type: ignore[union-attr]
        assert parsed.related_phases == original.related_phases
        assert parsed.summary == original.summary
        assert parsed.evidence == original.evidence
        assert parsed.impact == original.impact

    def test_missing_frontmatter_raises(self) -> None:
        from consilium.plan.parser import PlanParseError

        with pytest.raises(PlanParseError):
            parse_finding("# No frontmatter\n")
