"""Browser manager for multi-account support.

Manages a single active BrowserClient, switching between account profiles.
Only one Playwright persistent context can be active at a time.
"""

import asyncio
import logging

from app.browser.client import BrowserClient
from app.services.account_service import AccountService

logger = logging.getLogger(__name__)


class BrowserManager:
    """Manages a single active BrowserClient, switching between accounts."""

    def __init__(self, account_service: AccountService) -> None:
        self._account_service = account_service
        self._current_client: BrowserClient | None = None
        self._current_account_id: str | None = None
        self._lock = asyncio.Lock()

    @property
    def current_account_id(self) -> str | None:
        """The account ID of the currently active browser context."""
        return self._current_account_id

    async def get_client(self, account_id: str | None = None) -> BrowserClient:
        """Get or create a BrowserClient for the given account.

        If account_id is None, uses the active account from the registry.
        If the requested account differs from the current one, switches.

        Raises:
            ValueError: If no account is available.
        """
        async with self._lock:
            if account_id is None:
                account_id = self._account_service.get_active_account_id()
            if account_id is None:
                raise ValueError("No active account. Please add an account first.")

            # Reuse existing client if it matches
            if (
                self._current_client is not None
                and self._current_client.is_initialized
                and self._current_account_id == account_id
            ):
                return self._current_client

            # Stop the old client
            await self._stop_current()

            # Start a new client for the requested account
            profile_dir = self._account_service.get_profile_dir(account_id)
            profile_dir.mkdir(parents=True, exist_ok=True)

            client = BrowserClient(user_data_dir=profile_dir)
            await client.start()

            self._current_client = client
            self._current_account_id = account_id
            logger.info("Browser started for account %s", account_id)
            return client

    async def switch_account(self, account_id: str) -> BrowserClient:
        """Switch to a different account's browser context.

        Raises:
            ValueError: If account_id is not found.
        """
        # Validate account exists
        self._account_service.set_active_account(account_id)
        return await self.get_client(account_id)

    async def stop_current(self) -> None:
        """Stop the current browser client (public)."""
        async with self._lock:
            await self._stop_current()

    async def _stop_current(self) -> None:
        """Stop the current browser client (internal, assumes lock held)."""
        if self._current_client is not None:
            try:
                await self._current_client.stop()
            except Exception as e:
                logger.warning("Error stopping browser client: %s", e)
            self._current_client = None
            self._current_account_id = None

    async def shutdown(self) -> None:
        """Stop any active client. Called on app shutdown."""
        await self.stop_current()
        logger.info("BrowserManager shut down")
