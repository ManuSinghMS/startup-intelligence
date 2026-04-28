"""
Tests for the founder-weighted relevance scoring module.
"""
import pytest
from src.scoring.relevance import (
    score_relevance,
    _normalize_company,
    _parse_person_names,
    _name_variants,
)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestNormalizeCompany:
    def test_basic(self):
        variants = _normalize_company("FooBar Inc.")
        assert "foobar inc." in variants
        assert "foobar" in variants

    def test_no_suffix(self):
        variants = _normalize_company("Acme")
        assert variants == ["acme"]

    def test_empty(self):
        assert _normalize_company("") == []
        assert _normalize_company(None) == []

    def test_llc(self):
        variants = _normalize_company("TestCo LLC")
        assert "testco" in variants


class TestParsePersonNames:
    def test_single(self):
        assert _parse_person_names("John Smith") == ["John Smith"]

    def test_comma_separated(self):
        names = _parse_person_names("Alice Jones, Bob Brown")
        assert len(names) == 2
        assert "Alice Jones" in names
        assert "Bob Brown" in names

    def test_and_separator(self):
        names = _parse_person_names("Alice and Bob")
        assert len(names) == 2

    def test_empty(self):
        assert _parse_person_names("") == []
        assert _parse_person_names(None) == []

    def test_short_name_filtered(self):
        assert _parse_person_names("AB") == []


class TestNameVariants:
    def test_full_name(self):
        variants = _name_variants("John Smith")
        assert "john smith" in variants
        assert "smith" in variants
        assert "j. smith" in variants
        assert "j smith" in variants

    def test_single_name(self):
        variants = _name_variants("Madonna")
        assert "madonna" in variants
        assert len(variants) == 1  # No last-name variants for single names

    def test_empty(self):
        assert _name_variants("") == []


# ---------------------------------------------------------------------------
# Core scoring tests
# ---------------------------------------------------------------------------

class TestScoreRelevance:
    """Test the founder-weighted scoring logic."""

    def test_founder_in_title_high_score(self):
        """Founder name in title should give highest score (~0.90)."""
        relevant, score = score_relevance(
            title="John Smith raises $5M for new AI startup",
            content="The company was founded last year.",
            company_name="NewAI Corp",
            founder_names="John Smith",
        )
        assert relevant
        assert score >= 0.85

    def test_founder_in_body_medium_score(self):
        """Founder name in body (not title) should give medium score (~0.70)."""
        relevant, score = score_relevance(
            title="New AI startup raises funding round",
            content="CEO John Smith announced the Series A.",
            company_name="NewAI Corp",
            founder_names="John Smith",
        )
        assert relevant
        assert 0.65 <= score <= 0.80

    def test_company_in_title_moderate_score(self):
        """Company name in title (no founder) should give moderate score (~0.50)."""
        relevant, score = score_relevance(
            title="NewAI Corp launches new product",
            content="The product is designed for enterprises.",
            company_name="NewAI Corp",
            founder_names="",
        )
        assert relevant
        assert 0.45 <= score <= 0.55

    def test_company_in_body_only_low_score(self):
        """Company name in body only should give low score (~0.30)."""
        relevant, score = score_relevance(
            title="Startup landscape heats up",
            content="Companies like NewAI Corp are leading the way.",
            company_name="NewAI Corp",
            founder_names="",
        )
        assert relevant
        assert 0.25 <= score <= 0.35

    def test_founder_plus_company_highest_score(self):
        """Both founder AND company match should give highest score (capped at 1.0)."""
        relevant, score = score_relevance(
            title="John Smith of NewAI Corp wins innovation award",
            content="The founder was recognized for his contributions.",
            company_name="NewAI Corp",
            founder_names="John Smith",
        )
        assert relevant
        assert score >= 0.95

    def test_company_name_changed_founder_still_matches(self):
        """If company renamed but founder matches, should still score highly."""
        relevant, score = score_relevance(
            title="John Smith launches rebrand for his startup venture",
            content="The AI-focused company is now called SuperAI.",
            company_name="SuperAI",  # New name
            founder_names="John Smith",  # Same founder
        )
        assert relevant
        assert score >= 0.85  # Founder match is primary signal

    def test_no_match_zero_score(self):
        """No match at all should return not relevant, 0.0."""
        relevant, score = score_relevance(
            title="Weather forecast for Tuesday",
            content="Expect rain in the afternoon.",
            company_name="NewAI Corp",
            founder_names="John Smith",
        )
        assert not relevant
        assert score == 0.0

    def test_cofounder_matches_too(self):
        """Co-founder names should be scored just like founder names."""
        relevant, score = score_relevance(
            title="Jane Doe speaks at tech conference",
            content="The co-founder discussed future of AI.",
            company_name="TestCo",
            founder_names="John Smith",
            cofounder_names="Jane Doe",
        )
        assert relevant
        assert score >= 0.85

    def test_contact_name_fallback(self):
        """contact_name should be used as fallback if no founder fields."""
        relevant, score = score_relevance(
            title="Alice Johnson presents at demo day",
            content="The startup incubator event.",
            company_name="TestCo",
            founder_names=None,
            cofounder_names=None,
            contact_name="Alice Johnson",
        )
        assert relevant
        assert score >= 0.85

    def test_company_suffix_stripped(self):
        """Company name with Inc./Corp. stripped should still match."""
        relevant, score = score_relevance(
            title="TestCo announces new product line",
            content="The product launch event.",
            company_name="TestCo Inc.",
            founder_names="",
        )
        assert relevant
        assert score >= 0.45

    def test_legal_name_match(self):
        """Legal name should be checked as a secondary company name."""
        relevant, score = score_relevance(
            title="TestCo Legal Name Ltd launches widget",
            content="The new widget is revolutionary.",
            company_name="TestCo Common Name",
            legal_name="TestCo Legal Name Ltd",
            founder_names="",
        )
        assert relevant
        assert score >= 0.45

    def test_short_company_name_protected(self):
        """Very short company names (< 3 chars) should not match."""
        relevant, score = score_relevance(
            title="AI is transforming the world",
            content="Many new companies are building AI products.",
            company_name="AI",
            founder_names="",
        )
        assert not relevant

    def test_fuzzy_founder_initial(self):
        """'J. Smith' should match founder 'John Smith'."""
        relevant, score = score_relevance(
            title="J. Smith wins startup award",
            content="Article about the winner.",
            company_name="TestCo",
            founder_names="John Smith",
        )
        assert relevant
        assert score >= 0.85

    def test_multiple_founders_any_match(self):
        """If any one of multiple founders matches, it should score."""
        relevant, score = score_relevance(
            title="Bob Brown interviewed by TechCrunch",
            content="The co-founder discussed expansion plans.",
            company_name="TestCo",
            founder_names="Alice Jones",
            cofounder_names="Bob Brown, Charlie Davis",
        )
        assert relevant
        assert score >= 0.85


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
