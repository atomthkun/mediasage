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


class TestFactExtraction:
    """Test the LLM fact extraction step."""

    def test_extract_facts_returns_structured_data(self):
        """extract_facts should return an ExtractedFacts from research data."""
        from backend.recommender import RecommendationPipeline

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"origin_story": "Recorded in Reykjavik"}'
        mock_response.input_tokens = 100
        mock_response.output_tokens = 50
        mock_response.model = "test-model"
        mock_response.estimated_cost.return_value = 0.001
        mock_llm.generate.return_value = mock_response
        mock_llm.parse_json_response.return_value = {
            "origin_story": "Recorded in Reykjavik",
            "personnel": ["Jonsi"],
            "musical_style": "Post-rock with orchestral arrangements",
            "vocal_approach": "Mostly Icelandic vocals, Vonlenska on 2 tracks only",
            "cultural_context": "Breakthrough album internationally",
            "track_highlights": "Svefn-g-englar is the lead single",
            "common_misconceptions": "Often assumed to be entirely in Vonlenska but most tracks are in Icelandic",
            "source_coverage": "Wikipedia covers recording and reception well",
        }

        pipeline = RecommendationPipeline(config=MagicMock(), llm_client=mock_llm)

        rd = ResearchData(
            wikipedia_summary="Agaetis byrjun is the second album by Sigur Ros...",
            track_listing=["Intro", "Svefn-g-englar", "Staralfur"],
            label="Smekkleysa",
            release_date="1999-06-12",
            credits={"Primary Artist": "Sigur Ros"},
            review_texts=["A landmark post-rock album..."],
        )

        facts = pipeline.extract_facts(
            artist="Sigur Ros",
            album="Agaetis byrjun",
            research=rd,
            session_id="test-session",
        )

        assert isinstance(facts, ExtractedFacts)
        assert "Vonlenska" in facts.vocal_approach
        assert "Icelandic" in facts.vocal_approach
        mock_llm.generate.assert_called_once()

    def test_extract_facts_includes_all_sources_in_prompt(self):
        """extract_facts should pass Wikipedia, reviews, and track listing to LLM."""
        from backend.recommender import RecommendationPipeline

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.input_tokens = 100
        mock_response.output_tokens = 50
        mock_response.model = "test-model"
        mock_response.estimated_cost.return_value = 0.001
        mock_llm.generate.return_value = mock_response
        mock_llm.parse_json_response.return_value = {
            "origin_story": "", "personnel": [], "musical_style": "",
            "vocal_approach": "", "cultural_context": "", "track_highlights": "",
            "common_misconceptions": "", "source_coverage": "",
        }

        pipeline = RecommendationPipeline(config=MagicMock(), llm_client=mock_llm)

        rd = ResearchData(
            wikipedia_summary="Wikipedia content here",
            review_texts=["Pitchfork review content", "Stereogum review content"],
            track_listing=["Track One", "Track Two"],
            label="Test Label",
            release_date="2020",
        )

        pipeline.extract_facts(
            artist="Test Artist", album="Test Album",
            research=rd, session_id="test",
        )

        # Verify the prompt includes all source material
        call_args = mock_llm.generate.call_args
        prompt = call_args[0][0]  # First positional arg is the user prompt
        assert "Wikipedia content here" in prompt
        assert "Pitchfork review content" in prompt
        assert "Stereogum review content" in prompt
        assert "Track One" in prompt
        assert "Test Label" in prompt

    def test_extract_facts_handles_empty_research(self):
        """extract_facts should handle research with no Wikipedia or reviews."""
        from backend.recommender import RecommendationPipeline

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.input_tokens = 10
        mock_response.output_tokens = 10
        mock_response.model = "test-model"
        mock_response.estimated_cost.return_value = 0.0
        mock_llm.generate.return_value = mock_response
        mock_llm.parse_json_response.return_value = {
            "origin_story": "NOT IN SOURCES",
            "personnel": [],
            "musical_style": "NOT IN SOURCES",
            "vocal_approach": "NOT IN SOURCES",
            "cultural_context": "NOT IN SOURCES",
            "track_highlights": "",
            "common_misconceptions": "",
            "source_coverage": "No Wikipedia or review sources available",
        }

        pipeline = RecommendationPipeline(config=MagicMock(), llm_client=mock_llm)

        rd = ResearchData(
            label="Test Label",
            track_listing=["Track 1"],
        )

        facts = pipeline.extract_facts(
            artist="Test", album="Test", research=rd, session_id="test",
        )

        assert isinstance(facts, ExtractedFacts)
