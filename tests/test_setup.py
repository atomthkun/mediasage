"""Tests for setup/onboarding endpoints."""

import pytest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.models import DefaultsConfig


@pytest.fixture
def client():
    """Create test client with mocked dependencies.

    Patches lifespan-triggered side effects (config loading, Plex/LLM init,
    library cache DB creation) so tests don't depend on real environment.
    """
    from backend.main import app
    with (
        patch("backend.main.get_config", return_value=create_mock_config()),
        patch("backend.main.init_plex_client"),
        patch("backend.main.init_llm_client"),
        patch("backend.main.library_cache"),
    ):
        return TestClient(app)


def create_mock_config(**overrides):
    """Create a properly structured mock config for setup tests."""
    defaults = {
        "plex_url": "http://test:32400",
        "plex_token": "token",
        "music_library": "Music",
        "llm_provider": "anthropic",
        "llm_api_key": "key",
        "model_analysis": "claude-sonnet-4-5",
        "model_generation": "claude-haiku-4-5",
        "ollama_url": "http://localhost:11434",
        "custom_url": "",
    }
    defaults.update(overrides)
    mock = MagicMock()
    mock.plex.url = defaults["plex_url"]
    mock.plex.token = defaults["plex_token"]
    mock.plex.music_library = defaults["music_library"]
    mock.llm.provider = defaults["llm_provider"]
    mock.llm.api_key = defaults["llm_api_key"]
    mock.llm.model_analysis = defaults["model_analysis"]
    mock.llm.model_generation = defaults["model_generation"]
    mock.llm.ollama_url = defaults["ollama_url"]
    mock.llm.custom_url = defaults["custom_url"]
    mock.defaults = DefaultsConfig(track_count=25)
    return mock


class TestSetupStatus:
    """Tests for GET /api/setup/status."""

    def test_status_returns_all_fields(self, client):
        """Should return full checklist state."""
        mock_plex = MagicMock()
        mock_plex.is_connected.return_value = True
        mock_plex.get_error.return_value = None
        mock_plex.get_music_libraries.return_value = ["Music"]

        with (
            patch("backend.main.get_config", return_value=create_mock_config()),
            patch("backend.main.get_plex_client", return_value=mock_plex),
            patch("backend.main.library_cache") as mock_cache,
            patch("backend.main.load_user_yaml_config", return_value={}),
        ):
            mock_cache.DATA_DIR = MagicMock()
            mock_cache.DATA_DIR.mkdir = MagicMock()
            # Simulate writable dir — __truediv__ returns a path-like mock
            test_file = MagicMock()
            mock_cache.DATA_DIR.__truediv__ = MagicMock(return_value=test_file)
            mock_cache.has_cached_tracks.return_value = True
            mock_cache.get_sync_state.return_value = {
                "track_count": 1000,
                "synced_at": "2026-01-01T00:00:00",
                "is_syncing": False,
                "sync_progress": None,
                "error": None,
            }

            response = client.get("/api/setup/status")

        assert response.status_code == 200
        data = response.json()
        assert data["plex_connected"] is True
        assert data["llm_configured"] is True
        assert data["library_synced"] is True
        assert data["track_count"] == 1000
        assert data["setup_complete"] is False
        assert data["music_libraries"] == ["Music"]

    def test_status_unconfigured(self, client):
        """Should show all steps incomplete when nothing is configured."""
        with (
            patch("backend.main.get_config", return_value=create_mock_config(
                plex_url="", plex_token="", llm_api_key=""
            )),
            patch("backend.main.get_plex_client", return_value=None),
            patch("backend.main.library_cache") as mock_cache,
            patch("backend.main.load_user_yaml_config", return_value={}),
        ):
            mock_cache.DATA_DIR = MagicMock()
            mock_cache.DATA_DIR.mkdir = MagicMock()
            test_file = MagicMock()
            mock_cache.DATA_DIR.__truediv__ = MagicMock(return_value=test_file)
            mock_cache.has_cached_tracks.return_value = False
            mock_cache.get_sync_state.return_value = {
                "track_count": 0,
                "synced_at": None,
                "is_syncing": False,
                "sync_progress": None,
                "error": None,
            }

            response = client.get("/api/setup/status")

        assert response.status_code == 200
        data = response.json()
        assert data["plex_connected"] is False
        assert data["llm_configured"] is False
        assert data["library_synced"] is False
        assert data["setup_complete"] is False

    def test_status_setup_complete(self, client):
        """Should reflect setup_complete from config.user.yaml."""
        with (
            patch("backend.main.get_config", return_value=create_mock_config()),
            patch("backend.main.get_plex_client", return_value=None),
            patch("backend.main.library_cache") as mock_cache,
            patch("backend.main.load_user_yaml_config", return_value={"setup": {"complete": True}}),
        ):
            mock_cache.DATA_DIR = MagicMock()
            mock_cache.DATA_DIR.mkdir = MagicMock()
            test_file = MagicMock()
            mock_cache.DATA_DIR.__truediv__ = MagicMock(return_value=test_file)
            mock_cache.has_cached_tracks.return_value = False
            mock_cache.get_sync_state.return_value = {
                "track_count": 0, "synced_at": None,
                "is_syncing": False, "sync_progress": None, "error": None,
            }

            response = client.get("/api/setup/status")

        assert response.status_code == 200
        assert response.json()["setup_complete"] is True


class TestSetupValidatePlex:
    """Tests for POST /api/setup/validate-plex."""

    def test_validate_plex_success(self, client):
        """Should return success when Plex connects."""
        mock_temp_client = MagicMock()
        mock_temp_client.is_connected.return_value = True
        mock_temp_client.get_music_libraries.return_value = ["Music", "Audiobooks"]
        mock_temp_client._server = MagicMock()
        mock_temp_client._server.friendlyName = "My Plex Server"

        with (
            patch("backend.main.PlexClientInstance", return_value=mock_temp_client),
            patch("backend.main.update_config_values"),
            patch("backend.main.init_plex_client"),
        ):
            response = client.post("/api/setup/validate-plex", json={
                "plex_url": "http://plex:32400",
                "plex_token": "abc123",
                "music_library": "Music",
            })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["server_name"] == "My Plex Server"
        assert data["music_libraries"] == ["Music", "Audiobooks"]

    def test_validate_plex_failure(self, client):
        """Should return error when Plex connection fails."""
        mock_temp_client = MagicMock()
        mock_temp_client.is_connected.return_value = False
        mock_temp_client.get_error.return_value = "Invalid Plex token - unauthorized"

        with patch("backend.main.PlexClientInstance", return_value=mock_temp_client):
            response = client.post("/api/setup/validate-plex", json={
                "plex_url": "http://plex:32400",
                "plex_token": "bad-token",
                "music_library": "Music",
            })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "unauthorized" in data["error"].lower()


class TestSetupValidateAI:
    """Tests for POST /api/setup/validate-ai."""

    def test_validate_ollama_success(self, client):
        """Should validate Ollama by checking connection status."""
        mock_status = MagicMock()
        mock_status.connected = True

        with (
            patch("backend.main.get_ollama_status", return_value=mock_status),
            patch("backend.main.update_config_values", return_value=create_mock_config(llm_provider="ollama")),
            patch("backend.main.init_llm_client"),
        ):
            response = client.post("/api/setup/validate-ai", json={
                "provider": "ollama",
                "ollama_url": "http://localhost:11434",
            })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Ollama" in data["provider_name"]

    def test_validate_ollama_failure(self, client):
        """Should return error when Ollama is unreachable."""
        mock_status = MagicMock()
        mock_status.connected = False
        mock_status.error = "Connection refused"

        with patch("backend.main.get_ollama_status", return_value=mock_status):
            response = client.post("/api/setup/validate-ai", json={
                "provider": "ollama",
                "ollama_url": "http://localhost:11434",
            })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] is not None

    def test_validate_unknown_provider(self, client):
        """Should reject unknown providers."""
        response = client.post("/api/setup/validate-ai", json={
            "provider": "nonexistent",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Unknown provider" in data["error"]

    def test_validate_gemini_success(self, client):
        """Should validate Gemini by listing models."""
        mock_client_instance = MagicMock()
        mock_client_instance.models.list.return_value = [MagicMock()]

        with (
            patch("google.genai.Client", return_value=mock_client_instance),
            patch("backend.main.update_config_values", return_value=create_mock_config(llm_provider="gemini")),
            patch("backend.main.init_llm_client"),
        ):
            response = client.post("/api/setup/validate-ai", json={
                "provider": "gemini",
                "api_key": "test-key",
            })

        assert response.status_code == 200
        assert response.json()["success"] is True


class TestSetupComplete:
    """Tests for POST /api/setup/complete."""

    def test_complete_saves_flag(self, client):
        """Should save setup.complete to config.user.yaml."""
        with patch("backend.main.save_user_config") as mock_save:
            response = client.post("/api/setup/complete")

        assert response.status_code == 200
        assert response.json()["success"] is True
        mock_save.assert_called_once_with({"setup": {"complete": True}})

    def test_complete_handles_save_error(self, client):
        """Should still return success even if save fails (best-effort)."""
        with patch("backend.main.save_user_config", side_effect=Exception("disk full")):
            response = client.post("/api/setup/complete")

        assert response.status_code == 200
        assert response.json()["success"] is True
