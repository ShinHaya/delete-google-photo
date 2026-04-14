"""Google authentication flow for browser automation."""

import asyncio
import contextlib
import logging

from app.browser.client import BrowserClient
from app.exceptions import AuthenticationError, SessionExpiredError

logger = logging.getLogger(__name__)


class GoogleAuthenticator:
    """Handles Google authentication for browser automation."""

    LOGIN_URL = "https://accounts.google.com/signin"
    PHOTOS_URL = "https://photos.google.com"

    def __init__(self, browser_client: BrowserClient) -> None:
        """Initialize authenticator.

        Args:
            browser_client: Browser client instance
        """
        self.client = browser_client

    async def is_authenticated(self) -> bool:
        """Check if currently authenticated.

        Returns:
            True if authenticated, False otherwise
        """
        return await self.client.is_logged_in()

    async def wait_for_manual_login(
        self,
        timeout: int = 300,
        check_interval: int = 5,
    ) -> bool:
        """Wait for user to manually complete login.

        This method navigates to the Google account login page and waits
        for the user to complete the login process manually. This is
        necessary because Google's login flow includes various security
        measures that make automated login difficult and potentially
        against ToS.

        Args:
            timeout: Maximum time to wait in seconds (default: 5 minutes)
            check_interval: Interval between login checks in seconds

        Returns:
            True if login successful within timeout

        Raises:
            AuthenticationError: If login times out
        """
        logger.info("Navigating to Google login page...")
        page = self.client.page
        # Google's sign-in page triggers redirect chains that can abort the
        # initial navigation with net::ERR_ABORTED. Use domcontentloaded and
        # swallow aborts — the subsequent login-state polling will confirm
        # the real URL.
        with contextlib.suppress(Exception):
            await page.goto(self.LOGIN_URL, wait_until="domcontentloaded")

        # If already on login page or not logged in, wait for login
        start_time = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time

            if elapsed > timeout:
                raise AuthenticationError(
                    f"Login timeout: User did not complete login within {timeout} seconds"
                )

            # Check if we're now logged in
            if await self._check_logged_in_state():
                logger.info("Login detected successfully!")
                await self.client.save_state()
                return True

            remaining = int(timeout - elapsed)
            logger.info(
                "Waiting for login... (%d seconds remaining). "
                "Please complete the login in the browser window.",
                remaining,
            )

            await asyncio.sleep(check_interval)

    async def _check_logged_in_state(self) -> bool:
        """Check if currently logged in.

        While the browser is anywhere under ``accounts.google.com`` we are
        still in the sign-in flow (identifier / password / challenge /
        account chooser / transient redirects), so we must NOT navigate
        away — doing so would kick the user off the login form and send
        them to Google Photos. Once Google redirects to a different host
        (typically ``myaccount.google.com`` or the ``continue`` target),
        we delegate to ``client.is_logged_in()`` to confirm via Photos.

        Returns:
            True if logged in, False otherwise
        """
        try:
            page = self.client.page
            current_url = page.url

            # about:blank / blank tabs: still initializing, not done
            if not current_url or current_url.startswith(("about:", "chrome:")):
                return False

            # Any URL under accounts.google.com means sign-in is still
            # in progress (or the initial goto hasn't redirected yet).
            if "://accounts.google.com" in current_url:
                return False

            return await self.client.is_logged_in()

        except Exception as e:
            logger.warning("Error checking login state: %s", e)
            return False

    async def extract_account_email(self) -> str | None:
        """Extract the logged-in Google account email address.

        Best-effort: navigates to myaccount.google.com to find the email.
        Returns None if extraction fails.
        """
        page = self.client.page
        try:
            with contextlib.suppress(Exception):
                await page.goto(
                    "https://myaccount.google.com/",
                    wait_until="domcontentloaded",
                )

            # Strategy 1: the Google Account avatar button carries an
            # aria-label like "Google アカウント: 氏名 (user@gmail.com)".
            # This is the most reliable signal and works on every Google
            # property when signed in.
            # Strategy 2: look for the profile email text in common
            # myaccount.google.com selectors.
            # Strategy 3: fall back to mailto/data-email / regex over body.
            # We retry a few times because myaccount can render slowly.
            for _ in range(10):
                email = await page.evaluate(
                    r"""
                    () => {
                        const emailRe = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/;

                        // 1. Avatar button aria-label
                        const aria = document.querySelectorAll('[aria-label]');
                        for (const el of aria) {
                            const label = el.getAttribute('aria-label') || '';
                            const m = label.match(emailRe);
                            if (m) return m[0];
                        }

                        // 2. mailto / data-email attributes
                        const direct = document.querySelectorAll(
                            'a[href^="mailto:"], [data-email], [data-initial-email]'
                        );
                        for (const el of direct) {
                            const href = el.getAttribute('href') || '';
                            if (href.startsWith('mailto:')) return href.slice(7);
                            const de = el.getAttribute('data-email')
                                || el.getAttribute('data-initial-email');
                            if (de && emailRe.test(de)) return de;
                        }

                        // 3. Visible text fallback
                        const body = document.body ? document.body.innerText : '';
                        const m = body.match(emailRe);
                        return m ? m[0] : null;
                    }
                    """
                )
                if email:
                    logger.info("Extracted account email: %s", email)
                    return str(email)
                await asyncio.sleep(0.5)

            logger.warning("Could not extract email from account page")
            return None

        except Exception as e:
            logger.warning("Failed to extract account email: %s", e)
            return None

    async def ensure_authenticated(
        self,
        auto_prompt: bool = True,
        timeout: int = 300,
    ) -> bool:
        """Ensure user is authenticated, prompting for login if needed.

        Args:
            auto_prompt: If True, automatically prompt for manual login
            timeout: Timeout for login in seconds

        Returns:
            True if authenticated

        Raises:
            AuthenticationError: If authentication fails
        """
        if await self.is_authenticated():
            logger.info("Already authenticated")
            return True

        if not auto_prompt:
            raise AuthenticationError("Not authenticated and auto_prompt is disabled")

        logger.info("Not authenticated, prompting for manual login...")
        return await self.wait_for_manual_login(timeout=timeout)

    async def logout(self) -> None:
        """Logout from Google account and clear session."""
        try:
            await self.client.clear_state()
            logger.info("Logged out and cleared session state")
        except Exception as e:
            logger.error("Error during logout: %s", e)
            raise AuthenticationError(f"Failed to logout: {e}") from e

    async def refresh_session(self) -> bool:
        """Attempt to refresh the session if it has expired.

        Returns:
            True if session is valid or was refreshed successfully

        Raises:
            SessionExpiredError: If session cannot be refreshed
        """
        if await self.is_authenticated():
            return True

        # Try to reload the page to trigger session refresh
        try:
            page = self.client.page
            await page.reload()
            await page.wait_for_load_state("networkidle", timeout=10000)

            if await self.is_authenticated():
                logger.info("Session refreshed successfully")
                return True

        except Exception as e:
            logger.warning("Failed to refresh session: %s", e)

        raise SessionExpiredError("Session has expired. Please login again.")
