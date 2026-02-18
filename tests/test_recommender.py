"""Tests for the recommendation pipeline grounding improvements."""

from backend.models import (
    ExtractedFacts,
    PitchIssue,
    PitchValidation,
    ResearchData,
)


class TestGroundingModels:
    """Test new Pydantic models for pitch grounding."""

    def test_extracted_facts_defaults(self):
        """ExtractedFacts should have sensible defaults for all fields."""
        facts = ExtractedFacts()
        assert facts.origin_story == ""
        assert facts.personnel == []
        assert facts.musical_style == ""
        assert facts.vocal_approach == ""
        assert facts.cultural_context == ""
        assert facts.track_highlights == ""
        assert facts.common_misconceptions == ""
        assert facts.source_coverage == ""

    def test_extracted_facts_populated(self):
        """ExtractedFacts should accept all fields."""
        facts = ExtractedFacts(
            origin_story="Recorded after Berman's death",
            personnel=["Cassandra Jenkins", "Stuart Bogie"],
            musical_style="Ambient folk",
            vocal_approach="Sung vocals with spoken word on Hard Drive",
            cultural_context="Released on Ba Da Bing! Records",
            track_highlights="Hard Drive features spoken word",
            common_misconceptions="Jenkins never toured with Berman",
            source_coverage="Wikipedia covers origin well; no reviews available",
        )
        assert "Berman" in facts.origin_story
        assert len(facts.personnel) == 2

    def test_pitch_validation_valid(self):
        """PitchValidation should represent a passing check."""
        result = PitchValidation(valid=True)
        assert result.valid is True
        assert result.issues == []

    def test_pitch_validation_with_issues(self):
        """PitchValidation should hold a list of issues."""
        result = PitchValidation(
            valid=False,
            issues=[
                PitchIssue(
                    claim="touring stint with David Berman",
                    problem="contradicts research",
                    correction="Jenkins rehearsed with Purple Mountains but Berman died before the tour began",
                ),
            ],
        )
        assert not result.valid
        assert len(result.issues) == 1
        assert "rehearsed" in result.issues[0].correction

    def test_research_data_review_texts(self):
        """ResearchData should support review_texts field."""
        rd = ResearchData(
            wikipedia_summary="Album summary here",
            review_texts=["Great album review from Pitchfork"],
        )
        assert len(rd.review_texts) == 1
        assert rd.review_texts[0].startswith("Great")

    def test_research_data_review_texts_default(self):
        """ResearchData.review_texts should default to empty list."""
        rd = ResearchData()
        assert rd.review_texts == []
