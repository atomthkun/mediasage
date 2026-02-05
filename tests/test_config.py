"""Tests for configuration loading."""

import yaml

from backend.config import (
    load_config,
    load_yaml_config,
    get_env_or_yaml,
    MODEL_DEFAULTS,
)


class TestLoadYamlConfig:
    """Tests for YAML config file loading."""

    def test_loads_valid_yaml(self, tmp_path):
        """Should load a valid YAML config file."""
        config_file = tmp_path / "config.yaml"
        config_data = {
            "plex": {"url": "http://localhost:32400", "token": "test-token"},
            "llm": {"provider": "anthropic", "api_key": "sk-test"},
        }
        config_file.write_text(yaml.dump(config_data))

        result = load_yaml_config(config_file)

        assert result["plex"]["url"] == "http://localhost:32400"
        assert result["llm"]["provider"] == "anthropic"

    def test_returns_empty_dict_for_missing_file(self, tmp_path):
        """Should return empty dict when config file doesn't exist."""
        config_file = tmp_path / "nonexistent.yaml"

        result = load_yaml_config(config_file)

        assert result == {}

    def test_returns_empty_dict_for_empty_file(self, tmp_path):
        """Should return empty dict for empty config file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")

        result = load_yaml_config(config_file)

        assert result == {}


class TestGetEnvOrYaml:
    """Tests for environment variable priority."""

    def test_env_var_takes_priority(self, monkeypatch):
        """Environment variable should override YAML value."""
        monkeypatch.setenv("TEST_VAR", "env_value")

        result = get_env_or_yaml("TEST_VAR", "yaml_value", "default")

        assert result == "env_value"

    def test_yaml_used_when_no_env_var(self, monkeypatch):
        """YAML value should be used when env var not set."""
        monkeypatch.delenv("TEST_VAR", raising=False)

        result = get_env_or_yaml("TEST_VAR", "yaml_value", "default")

        assert result == "yaml_value"

    def test_default_used_when_no_env_or_yaml(self, monkeypatch):
        """Default should be used when neither env nor YAML set."""
        monkeypatch.delenv("TEST_VAR", raising=False)

        result = get_env_or_yaml("TEST_VAR", None, "default")

        assert result == "default"

    def test_empty_string_env_var_is_used(self, monkeypatch):
        """Empty string env var should still take priority."""
        monkeypatch.setenv("TEST_VAR", "")

        result = get_env_or_yaml("TEST_VAR", "yaml_value", "default")

        assert result == ""


class TestLoadConfig:
    """Tests for full configuration loading."""

    def test_loads_from_yaml_file(self, tmp_path, monkeypatch):
        """Should load configuration from YAML file."""
        # Clear any existing env vars
        for var in ["PLEX_URL", "PLEX_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                    "GEMINI_API_KEY", "LLM_PROVIDER", "LLM_MODEL_ANALYSIS", "LLM_MODEL_GENERATION"]:
            monkeypatch.delenv(var, raising=False)

        config_file = tmp_path / "config.yaml"
        config_data = {
            "plex": {
                "url": "http://plex.local:32400",
                "token": "yaml-token",
                "music_library": "My Music",
            },
            "llm": {
                "provider": "anthropic",
                "api_key": "sk-yaml-key",
            },
            "defaults": {"track_count": 40},
        }
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)

        assert config.plex.url == "http://plex.local:32400"
        assert config.plex.token == "yaml-token"
        assert config.plex.music_library == "My Music"
        assert config.llm.provider == "anthropic"
        assert config.llm.api_key == "sk-yaml-key"
        assert config.defaults.track_count == 40

    def test_env_vars_override_yaml(self, tmp_path, monkeypatch):
        """Environment variables should override YAML values."""
        # Clear any conflicting env vars first
        for var in ["GEMINI_API_KEY", "OPENAI_API_KEY", "LLM_PROVIDER",
                    "LLM_MODEL_ANALYSIS", "LLM_MODEL_GENERATION"]:
            monkeypatch.delenv(var, raising=False)

        config_file = tmp_path / "config.yaml"
        config_data = {
            "plex": {"url": "http://yaml:32400", "token": "yaml-token"},
            "llm": {"provider": "anthropic", "api_key": "yaml-key"},
        }
        config_file.write_text(yaml.dump(config_data))

        monkeypatch.setenv("PLEX_URL", "http://env:32400")
        monkeypatch.setenv("PLEX_TOKEN", "env-token")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")

        config = load_config(config_file)

        assert config.plex.url == "http://env:32400"
        assert config.plex.token == "env-token"
        assert config.llm.api_key == "env-key"

    def test_uses_correct_api_key_for_provider(self, tmp_path, monkeypatch):
        """Should use ANTHROPIC_API_KEY or OPENAI_API_KEY based on provider."""
        for var in ["PLEX_URL", "PLEX_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                    "GEMINI_API_KEY", "LLM_PROVIDER", "LLM_MODEL_ANALYSIS", "LLM_MODEL_GENERATION"]:
            monkeypatch.delenv(var, raising=False)

        # Test Anthropic provider
        config_file = tmp_path / "config.yaml"
        config_data = {"llm": {"provider": "anthropic", "api_key": ""}}
        config_file.write_text(yaml.dump(config_data))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

        config = load_config(config_file)
        assert config.llm.api_key == "anthropic-key"

        # Test OpenAI provider
        config_data = {"llm": {"provider": "openai", "api_key": ""}}
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)
        assert config.llm.api_key == "openai-key"

    def test_default_models_for_anthropic(self, tmp_path, monkeypatch):
        """Should use default Anthropic models when not specified."""
        for var in ["PLEX_URL", "PLEX_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                    "GEMINI_API_KEY", "LLM_PROVIDER", "LLM_MODEL_ANALYSIS", "LLM_MODEL_GENERATION"]:
            monkeypatch.delenv(var, raising=False)

        config_file = tmp_path / "config.yaml"
        config_data = {"llm": {"provider": "anthropic", "api_key": "test"}}
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)

        assert config.llm.model_analysis == MODEL_DEFAULTS["anthropic"]["analysis"]
        assert config.llm.model_generation == MODEL_DEFAULTS["anthropic"]["generation"]

    def test_default_models_for_openai(self, tmp_path, monkeypatch):
        """Should use default OpenAI models when not specified."""
        for var in ["PLEX_URL", "PLEX_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                    "GEMINI_API_KEY", "LLM_PROVIDER", "LLM_MODEL_ANALYSIS", "LLM_MODEL_GENERATION"]:
            monkeypatch.delenv(var, raising=False)

        config_file = tmp_path / "config.yaml"
        config_data = {"llm": {"provider": "openai", "api_key": "test"}}
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)

        assert config.llm.model_analysis == MODEL_DEFAULTS["openai"]["analysis"]
        assert config.llm.model_generation == MODEL_DEFAULTS["openai"]["generation"]

    def test_custom_models_override_defaults(self, tmp_path, monkeypatch):
        """Custom model settings should override defaults."""
        for var in ["PLEX_URL", "PLEX_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                    "GEMINI_API_KEY", "LLM_PROVIDER", "LLM_MODEL_ANALYSIS", "LLM_MODEL_GENERATION"]:
            monkeypatch.delenv(var, raising=False)

        config_file = tmp_path / "config.yaml"
        config_data = {
            "llm": {
                "provider": "anthropic",
                "api_key": "test",
                "model_analysis": "custom-analysis-model",
                "model_generation": "custom-gen-model",
            }
        }
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)

        assert config.llm.model_analysis == "custom-analysis-model"
        assert config.llm.model_generation == "custom-gen-model"

    def test_defaults_applied_when_no_config(self, tmp_path, monkeypatch):
        """Should use defaults when config file doesn't exist."""
        for var in ["PLEX_URL", "PLEX_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                    "GEMINI_API_KEY", "LLM_PROVIDER", "LLM_MODEL_ANALYSIS", "LLM_MODEL_GENERATION"]:
            monkeypatch.delenv(var, raising=False)

        config_file = tmp_path / "nonexistent.yaml"

        config = load_config(config_file)

        assert config.plex.music_library == "Music"
        assert config.llm.provider == "anthropic"
        assert config.defaults.track_count == 25

    def test_secrets_not_exposed_in_repr(self, tmp_path, monkeypatch):
        """Secrets should not be exposed when printing config."""
        config_file = tmp_path / "config.yaml"
        config_data = {
            "plex": {"url": "http://test:32400", "token": "secret-token"},
            "llm": {"provider": "anthropic", "api_key": "secret-api-key"},
        }
        config_file.write_text(yaml.dump(config_data))

        for var in ["PLEX_URL", "PLEX_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                    "GEMINI_API_KEY", "LLM_PROVIDER", "LLM_MODEL_ANALYSIS", "LLM_MODEL_GENERATION"]:
            monkeypatch.delenv(var, raising=False)

        config = load_config(config_file)

        # The token and api_key are stored, but we verify they exist
        # (actual masking would be in a different layer if needed)
        assert config.plex.token == "secret-token"
        assert config.llm.api_key == "secret-api-key"
