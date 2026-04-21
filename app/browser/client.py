"""Playwright browser client for Google Photos automation."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from app.config import settings
from app.exceptions import BrowserError

logger = logging.getLogger(__name__)


class BrowserClient:
    """Manages Playwright browser instance for Google Photos automation.

    Uses launch_persistent_context with the system Chrome (channel='chrome')
    to avoid Google's automated browser detection.
    """

    GOOGLE_PHOTOS_URL = "https://photos.google.com"

    def __init__(
        self,
        headless: bool | None = None,
        slow_mo: int | None = None,
        state_dir: Path | None = None,
        user_data_dir: Path | None = None,
    ) -> None:
        """Initialize browser client.

        Args:
            headless: Run browser in headless mode (default from settings)
            slow_mo: Slow down operations by specified milliseconds
            state_dir: Directory to store browser state (legacy, used when
                user_data_dir is not provided)
            user_data_dir: Explicit path to the browser user data directory.
                When provided, takes precedence over state_dir.
        """
        self.headless = headless if headless is not None else settings.headless
        self.slow_mo = slow_mo if slow_mo is not None else settings.slow_mo
        self.state_dir = state_dir or settings.browser_state_dir
        self._explicit_user_data_dir = user_data_dir

        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def user_data_dir(self) -> Path:
        """Path to persistent browser user data directory."""
        if self._explicit_user_data_dir is not None:
            return self._explicit_user_data_dir
        return self.state_dir / "chrome-profile"

    @property
    def is_initialized(self) -> bool:
        """Check if browser is initialized."""
        if self._context is None or self._page is None:
            return False
        try:
            return not self._page.is_closed()
        except Exception:
            return False

    @property
    def page(self) -> Page:
        """Get current page, raising error if not initialized."""
        if self._page is None:
            raise BrowserError("Browser page not initialized. Call start() first.")
        return self._page

    async def start(self) -> None:
        """Start browser with persistent context using system Chrome."""
        if self.is_initialized:
            logger.warning("Browser already initialized")
            return

        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            self._remove_stale_singleton_locks()

            self._playwright = await async_playwright().start()
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                channel="chrome",
                headless=self.headless,
                slow_mo=self.slow_mo,
                locale="ja-JP",
                args=[
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            # Use existing page or create new one
            if self._context.pages:
                self._page = self._context.pages[0]
            else:
                self._page = await self._context.new_page()

            logger.info("Browser started successfully (headless=%s)", self.headless)

        except Exception as e:
            await self.stop()
            raise BrowserError(f"Failed to start browser: {e}") from e

    async def stop(self) -> None:
        """Stop browser."""
        try:
            if self._context:
                await self._context.close()
                self._context = None

            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

            self._page = None
            logger.info("Browser stopped successfully")

        except Exception as e:
            logger.error("Error stopping browser: %s", e)
            raise BrowserError(f"Failed to stop browser: {e}") from e

    def _remove_stale_singleton_locks(self) -> None:
        """Remove stale Chrome Singleton* lock files from a previous crash.

        Chrome refuses to launch with a persistent profile if SingletonLock /
        SingletonCookie / SingletonSocket exist (they are symlinks or sockets
        pointing to the previous owning PID). If the previous process died
        uncleanly these files linger and block startup. Removing them is safe
        here because we guarantee via stop()/lifespan that no other instance
        should be using this profile.
        """
        profile_dir = self.user_data_dir
        if not profile_dir.exists():
            return
        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            p = profile_dir / name
            try:
                if p.is_symlink() or p.exists():
                    p.unlink()
                    logger.info("Removed stale %s at %s", name, p)
            except OSError as e:
                logger.warning("Could not remove %s: %s", p, e)

    async def save_state(self) -> None:
        """Save browser state.

        With persistent context, state (cookies, localStorage) is
        automatically saved to the user data directory.
        """
        logger.info("Browser state is auto-saved via persistent context")

    async def clear_state(self) -> None:
        """Clear saved browser state by removing the user data directory."""
        import shutil

        profile_dir = self.user_data_dir
        if profile_dir.exists():
            shutil.rmtree(profile_dir)
            logger.info("Browser profile cleared: %s", profile_dir)

    async def navigate_to_photos(self) -> None:
        """Navigate to Google Photos."""
        await self.page.goto(self.GOOGLE_PHOTOS_URL)
        logger.info("Navigated to Google Photos")

    async def is_logged_in(self) -> bool:
        """Check if user is logged in to Google Photos.

        Returns:
            True if logged in, False otherwise
        """
        try:
            await self.navigate_to_photos()
            await self.page.wait_for_load_state("networkidle", timeout=10000)

            current_url = self.page.url

            # If redirected to login page or about page, not logged in
            if "accounts.google.com" in current_url:
                return False
            if "google.com/photos/about" in current_url:
                return False

            # Check for photos UI elements
            try:
                await self.page.wait_for_selector(
                    '[data-page-type="main"], [role="main"]',
                    timeout=5000,
                )
                return True
            except Exception:
                return False

        except Exception as e:
            logger.warning("Error checking login status: %s", e)
            return False

    @asynccontextmanager
    async def session(self) -> AsyncGenerator["BrowserClient", None]:
        """Context manager for browser session."""
        await self.start()
        try:
            yield self
        finally:
            await self.stop()


@asynccontextmanager
async def get_browser_client(
    headless: bool | None = None,
    slow_mo: int | None = None,
    user_data_dir: Path | None = None,
) -> AsyncGenerator[BrowserClient, None]:
    """Get a browser client instance as a context manager.

    Args:
        headless: Run browser in headless mode
        slow_mo: Slow down operations by specified milliseconds
        user_data_dir: Explicit browser profile directory

    Yields:
        BrowserClient instance
    """
    client = BrowserClient(
        headless=headless, slow_mo=slow_mo, user_data_dir=user_data_dir
    )
    async with client.session():
        yield client
