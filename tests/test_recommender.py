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


import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestMusicResearchReviews:
    """Test review URL extraction and fetching in MusicResearchClient."""

    @pytest.mark.asyncio
    async def test_lookup_release_group_extracts_review_urls(self):
        """lookup_release_group should extract review-type URLs."""
        from backend.music_research import MusicResearchClient

        client = MusicResearchClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "relations": [
                {"type": "wikipedia", "url": {"resource": "https://en.wikipedia.org/wiki/Test_Album"}},
                {"type": "review", "url": {"resource": "https://pitchfork.com/reviews/albums/test/"}},
                {"type": "review", "url": {"resource": "https://stereogum.com/review/test/"}},
                {"type": "allmusic", "url": {"resource": "https://www.allmusic.com/album/test"}},
            ],
            "releases": [{"id": "rel-123", "date": "2020-01-01"}],
        }

        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.get = AsyncMock(return_value=mock_response)
        client._http = mock_http
        client._last_mb_request = 0

        result = await client.lookup_release_group("test-mbid")

        assert result is not None
        assert result["wikipedia_url"] == "https://en.wikipedia.org/wiki/Test_Album"
        assert "https://pitchfork.com/reviews/albums/test/" in result["review_urls"]
        assert "https://stereogum.com/review/test/" in result["review_urls"]
        # AllMusic should NOT be in review_urls (TOS)
        assert "https://www.allmusic.com/album/test" not in result.get("review_urls", [])

    @pytest.mark.asyncio
    async def test_fetch_review_text_extracts_article(self):
        """fetch_review_text should extract article text from HTML."""
        from backend.music_research import MusicResearchClient

        client = MusicResearchClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.text = """
        <html><head><title>Album Review</title></head>
        <body>
        <nav>Site Navigation</nav>
        <article>
        <h1>Album Review: Test Album</h1>
        <p>This is a detailed review of the album. The recording was made in a
        studio in Brooklyn with producer John Smith. The vocals are predominantly
        sung in English with some instrumental passages.</p>
        </article>
        <footer>Site Footer</footer>
        </body></html>
        """

        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.get = AsyncMock(return_value=mock_response)
        client._http = mock_http

        result = await client.fetch_review_text("https://example.com/review")

        assert result is not None
        assert "detailed review" in result
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_fetch_review_text_skips_allmusic(self):
        """fetch_review_text should refuse to fetch AllMusic URLs."""
        from backend.music_research import MusicResearchClient

        client = MusicResearchClient()
        result = await client.fetch_review_text("https://www.allmusic.com/album/test")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_review_text_handles_failure(self):
        """fetch_review_text should return None on HTTP errors."""
        from backend.music_research import MusicResearchClient

        client = MusicResearchClient()
        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.get = AsyncMock(side_effect=Exception("Connection refused"))
        client._http = mock_http

        result = await client.fetch_review_text("https://example.com/review")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_review_text_truncates_long_content(self):
        """fetch_review_text should truncate to ~2000 chars."""
        from backend.music_research import MusicResearchClient

        client = MusicResearchClient()
        long_text = "<html><body><article>" + ("x" * 5000) + "</article></body></html>"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.text = long_text

        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.get = AsyncMock(return_value=mock_response)
        client._http = mock_http

        result = await client.fetch_review_text("https://example.com/review")

        assert result is not None
        assert len(result) <= 2100  # Allow small margin for sentence boundary
