"""Configuration loading with environment variable priority."""

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from backend.models import AppConfig, DefaultsConfig, LLMConfig, PlexConfig

# Load .env file (if it exists) - env vars take priority
load_dotenv()


# Default model mappings per provider
MODEL_DEFAULTS = {
    "anthropic": {
        "analysis": "claude-sonnet-4-5",
        "generation": "claude-haiku-4-5",
    },
    "openai": {
        "analysis": "gpt-4.1",
        "generation": "gpt-4.1-mini",
    },
    "gemini": {
        "analysis": "gemini-2.5-flash",
        "generation": "gemini-2.5-flash",
    },
}


def load_yaml_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load configuration from YAML file."""
    if config_path is None:
        config_path = Path("config.yaml")

    if not config_path.exists():
        return {}

    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def get_env_or_yaml(
    env_key: str, yaml_value: Any, default: Any = None
) -> Any:
    """Get value from environment variable or fall back to YAML value."""
    env_value = os.environ.get(env_key)
    if env_value is not None:
        return env_value
    if yaml_value is not None:
        return yaml_value
    return default


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load configuration with environment variable priority.

    Priority order:
    1. Environment variables (highest)
    2. config.yaml file
    3. Default values (lowest)
    """
    yaml_config = load_yaml_config(config_path)

    # Extract nested config sections
    plex_yaml = yaml_config.get("plex", {})
    llm_yaml = yaml_config.get("llm", {})
    defaults_yaml = yaml_config.get("defaults", {})

    # Determine LLM provider - explicit setting or auto-detect from API keys
    explicit_provider = get_env_or_yaml(
        "LLM_PROVIDER", llm_yaml.get("provider"), None
    )

    # Check which API keys are available
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or llm_yaml.get("api_key", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")

    # Auto-detect provider if not explicitly set
    if explicit_provider:
        provider = explicit_provider
    elif gemini_key:
        provider = "gemini"
    elif openai_key:
        provider = "openai"
    elif anthropic_key:
        provider = "anthropic"
    else:
        provider = "gemini"  # Default

    # Get API key based on provider
    if provider == "anthropic":
        api_key = anthropic_key
    elif provider == "openai":
        api_key = openai_key
    elif provider == "gemini":
        api_key = gemini_key
    else:
        api_key = llm_yaml.get("api_key", "")

    # Get model defaults for the provider
    provider_defaults = MODEL_DEFAULTS.get(provider, MODEL_DEFAULTS["gemini"])

    # Build configuration
    plex_config = PlexConfig(
        url=get_env_or_yaml("PLEX_URL", plex_yaml.get("url"), ""),
        token=get_env_or_yaml("PLEX_TOKEN", plex_yaml.get("token"), ""),
        music_library=get_env_or_yaml(
            "PLEX_MUSIC_LIBRARY", plex_yaml.get("music_library"), "Music"
        ),
    )

    llm_config = LLMConfig(
        provider=provider,
        api_key=api_key,
        model_analysis=get_env_or_yaml(
            "LLM_MODEL_ANALYSIS",
            llm_yaml.get("model_analysis"),
            provider_defaults["analysis"],
        ),
        model_generation=get_env_or_yaml(
            "LLM_MODEL_GENERATION",
            llm_yaml.get("model_generation"),
            provider_defaults["generation"],
        ),
        smart_generation=llm_yaml.get("smart_generation", False),
    )

    defaults_config = DefaultsConfig(
        track_count=defaults_yaml.get("track_count", 25)
    )

    return AppConfig(
        plex=plex_config,
        llm=llm_config,
        defaults=defaults_config,
    )


# Global config instance (loaded on import, can be refreshed)
_config: AppConfig | None = None


def get_config() -> AppConfig:
    """Get the current configuration, loading if necessary."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def refresh_config(config_path: Path | None = None) -> AppConfig:
    """Reload configuration from file and environment."""
    global _config
    _config = load_config(config_path)
    return _config


def update_config_values(updates: dict[str, Any]) -> AppConfig:
    """Update specific configuration values in memory.

    Note: This does not persist changes to the YAML file.
    For Docker deployments, changes come via environment variables.
    """
    global _config
    if _config is None:
        _config = load_config()

    # Create updated config by merging updates
    plex_updates = {}
    llm_updates = {}

    if "plex_url" in updates and updates["plex_url"]:
        plex_updates["url"] = updates["plex_url"]
    if "plex_token" in updates and updates["plex_token"]:
        plex_updates["token"] = updates["plex_token"]
    if "music_library" in updates and updates["music_library"]:
        plex_updates["music_library"] = updates["music_library"]

    if "llm_provider" in updates and updates["llm_provider"]:
        new_provider = updates["llm_provider"]
        llm_updates["provider"] = new_provider

        # Auto-select API key from environment if provider changed and no key provided
        if not updates.get("llm_api_key"):
            env_keys = {
                "anthropic": os.environ.get("ANTHROPIC_API_KEY", ""),
                "openai": os.environ.get("OPENAI_API_KEY", ""),
                "gemini": os.environ.get("GEMINI_API_KEY", ""),
            }
            if env_keys.get(new_provider):
                llm_updates["api_key"] = env_keys[new_provider]

        # Auto-select default models for new provider
        if new_provider in MODEL_DEFAULTS:
            defaults = MODEL_DEFAULTS[new_provider]
            if not updates.get("model_analysis"):
                llm_updates["model_analysis"] = defaults["analysis"]
            if not updates.get("model_generation"):
                llm_updates["model_generation"] = defaults["generation"]

    if "llm_api_key" in updates and updates["llm_api_key"]:
        llm_updates["api_key"] = updates["llm_api_key"]
    if "model_analysis" in updates and updates["model_analysis"]:
        llm_updates["model_analysis"] = updates["model_analysis"]
    if "model_generation" in updates and updates["model_generation"]:
        llm_updates["model_generation"] = updates["model_generation"]

    # Create new config with updates
    new_plex = _config.plex.model_copy(update=plex_updates)
    new_llm = _config.llm.model_copy(update=llm_updates)

    _config = AppConfig(
        plex=new_plex,
        llm=new_llm,
        defaults=_config.defaults,
    )

    return _config
