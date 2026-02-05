"""Tests for LLM client."""

from unittest.mock import MagicMock, patch


class TestLLMClientInitialization:
    """Tests for LLM client initialization."""

    def test_anthropic_client_init(self, mocker):
        """Should initialize Anthropic client correctly."""
        from backend.llm_client import LLMClient
        from backend.models import LLMConfig

        config = LLMConfig(
            provider="anthropic",
            api_key="sk-ant-test-key",
            model_analysis="claude-sonnet-4-5-latest",
            model_generation="claude-haiku-4-5-latest",
        )

        with patch("backend.llm_client.anthropic") as mock_anthropic:
            client = LLMClient(config)
            mock_anthropic.Anthropic.assert_called_once_with(api_key="sk-ant-test-key")
            assert client.provider == "anthropic"

    def test_openai_client_init(self, mocker):
        """Should initialize OpenAI client correctly."""
        from backend.llm_client import LLMClient
        from backend.models import LLMConfig

        config = LLMConfig(
            provider="openai",
            api_key="sk-test-key",
            model_analysis="gpt-4.1",
            model_generation="gpt-4.1-mini",
        )

        with patch("backend.llm_client.openai") as mock_openai:
            client = LLMClient(config)
            mock_openai.OpenAI.assert_called_once_with(api_key="sk-test-key")
            assert client.provider == "openai"

    def test_invalid_api_key_anthropic(self, mocker):
        """Should handle invalid Anthropic API key."""
        from backend.llm_client import LLMClient
        from backend.models import LLMConfig

        config = LLMConfig(
            provider="anthropic",
            api_key="invalid-key",
            model_analysis="claude-sonnet-4-5-latest",
            model_generation="claude-haiku-4-5-latest",
        )

        with patch("backend.llm_client.anthropic") as mock_anthropic:
            mock_anthropic.Anthropic.return_value = MagicMock()
            client = LLMClient(config)
            # Client should be created; validation happens on first API call
            assert client.provider == "anthropic"

    def test_invalid_api_key_openai(self, mocker):
        """Should handle invalid OpenAI API key."""
        from backend.llm_client import LLMClient
        from backend.models import LLMConfig

        config = LLMConfig(
            provider="openai",
            api_key="invalid-key",
            model_analysis="gpt-4.1",
            model_generation="gpt-4.1-mini",
        )

        with patch("backend.llm_client.openai") as mock_openai:
            mock_openai.OpenAI.return_value = MagicMock()
            client = LLMClient(config)
            # Client should be created; validation happens on first API call
            assert client.provider == "openai"


class TestLLMClientAnalyze:
    """Tests for LLM analysis calls."""

    def test_analyze_uses_analysis_model(self, mocker):
        """Should use analysis model for analyze calls."""
        from backend.llm_client import LLMClient
        from backend.models import LLMConfig

        config = LLMConfig(
            provider="anthropic",
            api_key="test-key",
            model_analysis="claude-sonnet-4-5-latest",
            model_generation="claude-haiku-4-5-latest",
        )

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"result": "test"}')]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        with patch("backend.llm_client.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.Anthropic.return_value = mock_client

            client = LLMClient(config)
            client.analyze("test prompt", "system prompt")

            # Verify the analysis model was used
            call_args = mock_client.messages.create.call_args
            assert call_args.kwargs["model"] == "claude-sonnet-4-5-latest"


class TestLLMClientGenerate:
    """Tests for LLM generation calls."""

    def test_generate_uses_generation_model(self, mocker):
        """Should use generation model for generate calls."""
        from backend.llm_client import LLMClient
        from backend.models import LLMConfig

        config = LLMConfig(
            provider="anthropic",
            api_key="test-key",
            model_analysis="claude-sonnet-4-5-latest",
            model_generation="claude-haiku-4-5-latest",
            smart_generation=False,
        )

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='[{"artist": "Test", "title": "Song"}]')]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        with patch("backend.llm_client.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.Anthropic.return_value = mock_client

            client = LLMClient(config)
            client.generate("test prompt", "system prompt")

            # Verify the generation model was used
            call_args = mock_client.messages.create.call_args
            assert call_args.kwargs["model"] == "claude-haiku-4-5-latest"

    def test_smart_generation_uses_analysis_model(self, mocker):
        """Should use analysis model when smart_generation is enabled."""
        from backend.llm_client import LLMClient
        from backend.models import LLMConfig

        config = LLMConfig(
            provider="anthropic",
            api_key="test-key",
            model_analysis="claude-sonnet-4-5-latest",
            model_generation="claude-haiku-4-5-latest",
            smart_generation=True,
        )

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='[{"artist": "Test", "title": "Song"}]')]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        with patch("backend.llm_client.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.Anthropic.return_value = mock_client

            client = LLMClient(config)
            client.generate("test prompt", "system prompt")

            # Verify the analysis model was used for generation
            call_args = mock_client.messages.create.call_args
            assert call_args.kwargs["model"] == "claude-sonnet-4-5-latest"


class TestLLMClientTokenTracking:
    """Tests for token and cost tracking."""

    def test_tracks_tokens_anthropic(self, mocker):
        """Should track tokens for Anthropic calls."""
        from backend.llm_client import LLMClient
        from backend.models import LLMConfig

        config = LLMConfig(
            provider="anthropic",
            api_key="test-key",
            model_analysis="claude-sonnet-4-5-latest",
            model_generation="claude-haiku-4-5-latest",
        )

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"result": "test"}')]
        mock_response.usage.input_tokens = 150
        mock_response.usage.output_tokens = 75

        with patch("backend.llm_client.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.Anthropic.return_value = mock_client

            client = LLMClient(config)
            result = client.analyze("test prompt", "system prompt")

            assert result.input_tokens == 150
            assert result.output_tokens == 75
            assert result.total_tokens == 225

    def test_tracks_tokens_openai(self, mocker):
        """Should track tokens for OpenAI calls."""
        from backend.llm_client import LLMClient
        from backend.models import LLMConfig

        config = LLMConfig(
            provider="openai",
            api_key="test-key",
            model_analysis="gpt-4.1",
            model_generation="gpt-4.1-mini",
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content='{"result": "test"}'))]
        mock_response.usage.prompt_tokens = 150
        mock_response.usage.completion_tokens = 75

        with patch("backend.llm_client.openai") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai.OpenAI.return_value = mock_client

            client = LLMClient(config)
            result = client.analyze("test prompt", "system prompt")

            assert result.input_tokens == 150
            assert result.output_tokens == 75
            assert result.total_tokens == 225
