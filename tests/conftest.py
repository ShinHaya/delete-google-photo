"""Pytest configuration and shared fixtures."""

import tempfile
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import app


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_settings(temp_dir: Path) -> Settings:
    """Create test settings with temporary directories."""
    return Settings(
        environment="test",
        debug=True,
        state_dir=temp_dir / "state",
        browser_state_dir=temp_dir / "browser-state",
        headless=True,
    )


@pytest.fixture
def mock_settings(test_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Patch global settings with test settings."""
    monkeypatch.setattr("app.config.settings", test_settings)
    monkeypatch.setattr("app.main.settings", test_settings)
    monkeypatch.setattr("app.services.state_service.settings", test_settings)
    monkeypatch.setattr("app.services.account_service.settings", test_settings)
    monkeypatch.setattr("app.browser.client.settings", test_settings)
    monkeypatch.setattr("app.browser.operations.settings", test_settings)
    monkeypatch.setattr("app.utils.retry.settings", test_settings)
    return test_settings


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Create async HTTP client for testing API endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_photo_data() -> dict[str, Any]:
    """Sample photo data for testing."""
    return {
        "id": "photo_123",
        "filename": "IMG_001.jpg",
        "created_at": "2020-06-15T10:30:00Z",
        "url": "https://photos.google.com/photo/123",
    }


@pytest.fixture
def sample_state_data() -> dict[str, Any]:
    """Sample state data for testing."""
    return {
        "session_id": "test-session-123",
        "start_date": "2020-01-01",
        "end_date": "2020-12-31",
        "total_count": 100,
        "processed_count": 50,
        "last_processed_id": "photo_50",
        "status": "in_progress",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T01:00:00Z",
    }
