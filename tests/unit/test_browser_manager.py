"""Unit tests for BrowserManager lifecycle handling."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.browser.client import BrowserClient
from app.browser.manager import BrowserManager


class _StubAccountService:
    def __init__(self, profile_dir: Path) -> None:
        self._profile_dir = profile_dir

    def get_active_account_id(self) -> str:
        return "account-1"

    def get_profile_dir(self, account_id: str) -> Path:
        assert account_id == "account-1"
        return self._profile_dir

    def set_active_account(self, account_id: str) -> None:
        assert account_id == "account-1"


class TestBrowserClient:
    def test_is_initialized_false_when_page_closed(self, temp_dir: Path) -> None:
        client = BrowserClient(user_data_dir=temp_dir / "profile")
        client._context = MagicMock()
        client._page = MagicMock()
        client._page.is_closed.return_value = True

        assert client.is_initialized is False


class TestBrowserManager:
    @pytest.mark.asyncio
    async def test_get_client_restarts_when_existing_page_closed(
        self, temp_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = BrowserManager(_StubAccountService(temp_dir / "profile"))

        stale_client = MagicMock(spec=BrowserClient)
        stale_client.is_initialized = False
        stale_client.stop = AsyncMock()
        manager._current_client = stale_client
        manager._current_account_id = "account-1"

        fresh_client = MagicMock(spec=BrowserClient)
        fresh_client.start = AsyncMock()

        created_clients: list[MagicMock] = []

        def fake_browser_client(*, user_data_dir: Path) -> MagicMock:
            assert user_data_dir == temp_dir / "profile"
            created_clients.append(fresh_client)
            return fresh_client

        monkeypatch.setattr("app.browser.manager.BrowserClient", fake_browser_client)

        client = await manager.get_client()

        stale_client.stop.assert_awaited_once()
        fresh_client.start.assert_awaited_once()
        assert client is fresh_client
        assert manager.current_account_id == "account-1"
        assert created_clients == [fresh_client]
