"""FastAPI application entry point."""

import logging
import shutil
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.browser.manager import BrowserManager
from app.config import settings
from app.routers import accounts, health, photos
from app.services.account_service import AccountService

# Configure application logging. Without this, `logging.getLogger(__name__)`
# calls in app modules are silently dropped because no handler is attached.
# Uvicorn's --log-level flag only affects uvicorn's own loggers, not ours.
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)


_LEGACY_BROWSER_STATE_DIR = Path("state/browser-state")


def _prepare_browser_state_dir(target: Path) -> None:
    """Ensure the browser state directory exists with 0o700 permissions.

    Also performs a one-shot migration from the legacy in-project path
    (``state/browser-state/``) to the configured target location if the
    target is empty. This only runs on local macOS-style filesystems;
    failures are logged but non-fatal.
    """
    log = logging.getLogger(__name__)
    target = target.expanduser()

    try:
        legacy = _LEGACY_BROWSER_STATE_DIR.resolve()
    except OSError:
        legacy = _LEGACY_BROWSER_STATE_DIR
    try:
        resolved_target = target.resolve()
    except OSError:
        resolved_target = target

    target.mkdir(parents=True, exist_ok=True)
    try:
        target.chmod(0o700)
    except OSError as e:
        log.warning("Could not set 0o700 on %s: %s", target, e)

    if (
        legacy != resolved_target
        and legacy.exists()
        and any(legacy.iterdir())
        and not any(target.iterdir())
    ):
        log.info("Migrating browser state from %s to %s", legacy, target)
        try:
            for item in legacy.iterdir():
                shutil.move(str(item), str(target / item.name))
            legacy.rmdir()
        except OSError as e:
            log.warning("Browser state migration failed: %s", e)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    # Startup
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    _prepare_browser_state_dir(settings.browser_state_dir)

    # Initialize account management
    account_service = AccountService()
    browser_manager = BrowserManager(account_service)
    accounts.init_account_dependencies(account_service, browser_manager)

    # Recover any sessions left "in_progress" by a prior crash / restart.
    # Without this, the UI would never see them as resumable.
    try:
        await photos.recover_stale_in_progress_states()
    except Exception as e:  # noqa: BLE001 — startup must not be fatal here
        logging.getLogger(__name__).warning(
            "Failed to recover stale in_progress states: %s", e
        )

    try:
        yield
    finally:
        # Always shut down the browser, even on crash or reload, so the
        # persistent profile's Singleton* lock files are not left stale.
        try:
            await browser_manager.shutdown()
        except Exception as e:
            logging.getLogger(__name__).warning("Error during browser shutdown: %s", e)


app = FastAPI(
    title=settings.app_name,
    description="A tool to delete photos from Google Photos by date range",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Setup templates (autoescape is enabled by default in Jinja2)
templates = Jinja2Templates(directory="app/templates")

# Include routers
app.include_router(health.router)
app.include_router(photos.router)
app.include_router(accounts.router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the main page."""
    return templates.TemplateResponse(request, "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
