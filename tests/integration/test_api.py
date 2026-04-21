"""Integration tests for API endpoints."""

from collections.abc import Generator
from datetime import date

import pytest
from httpx import AsyncClient

from app.models.state import DeletionState, DeletionStatus
from app.routers import photos as photos_router
from app.services.state_service import StateService


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient) -> None:
        """Test health check returns healthy status."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestRootEndpoint:
    """Tests for root endpoint."""

    @pytest.mark.asyncio
    async def test_root_endpoint(self, client: AsyncClient) -> None:
        """Test root endpoint returns HTML page."""
        response = await client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert "Google Photos" in response.text


@pytest.fixture
def reset_active_session() -> Generator[None, None, None]:
    """Ensure module-level concurrency state starts and ends clean."""
    photos_router._active_session_id = None
    photos_router._active_tasks.clear()
    photos_router._cancellation_events.clear()
    yield
    photos_router._active_session_id = None
    photos_router._active_tasks.clear()
    photos_router._cancellation_events.clear()


class TestSessionEndpoints:
    """Tests for session polling, interrupt, and concurrency guards."""

    @pytest.mark.asyncio
    async def test_get_session_not_found(
        self,
        client: AsyncClient,
        mock_settings: object,  # noqa: ARG002 — patches global state_dir
        reset_active_session: None,  # noqa: ARG002
    ) -> None:
        response = await client.get("/api/photos/sessions/missing-id")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_session_returns_state(
        self,
        client: AsyncClient,
        mock_settings: object,  # noqa: ARG002
        reset_active_session: None,  # noqa: ARG002
    ) -> None:
        state = DeletionState(
            session_id="state-poll",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 31),
            total_count=10,
            processed_count=5,
            deleted_count=4,
            failed_count=1,
            failed_photo_ids=["x"],
            status=DeletionStatus.IN_PROGRESS,
        )
        await StateService().save(state)

        response = await client.get("/api/photos/sessions/state-poll")
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "state-poll"
        assert data["deleted_count"] == 4
        assert data["failed_count"] == 1
        assert data["failed_photo_ids"] == ["x"]
        assert data["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_interrupt_unknown_session_returns_404(
        self,
        client: AsyncClient,
        mock_settings: object,  # noqa: ARG002
        reset_active_session: None,  # noqa: ARG002
    ) -> None:
        response = await client.post("/api/photos/sessions/missing/interrupt")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_interrupt_marks_state_when_no_live_task(
        self,
        client: AsyncClient,
        mock_settings: object,  # noqa: ARG002
        reset_active_session: None,  # noqa: ARG002
    ) -> None:
        """Interrupting an in_progress session with no live task flips state."""
        state = DeletionState(
            session_id="orphaned",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 31),
            total_count=10,
            status=DeletionStatus.IN_PROGRESS,
        )
        await StateService().save(state)

        response = await client.post("/api/photos/sessions/orphaned/interrupt")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "interrupted"

    @pytest.mark.asyncio
    async def test_concurrency_guard_blocks_dry_run(
        self,
        client: AsyncClient,
        mock_settings: object,  # noqa: ARG002
        reset_active_session: None,
    ) -> None:
        """While a session holds the slot, dry-run must return 409."""
        photos_router._active_session_id = "fake-running"

        response = await client.post(
            "/api/photos/dry-run",
            json={"start_date": "2020-01-01", "end_date": "2020-01-31"},
        )

        assert response.status_code == 409
        # Cleanup handled by the fixture.
        del reset_active_session

    @pytest.mark.asyncio
    async def test_concurrency_guard_blocks_account_activate(
        self,
        client: AsyncClient,
        mock_settings: object,  # noqa: ARG002
        reset_active_session: None,
    ) -> None:
        """Account switching is blocked while a session is running."""
        photos_router._active_session_id = "fake-running"

        response = await client.post("/api/accounts/some-id/activate")
        assert response.status_code == 409
        del reset_active_session

    @pytest.mark.asyncio
    async def test_concurrency_guard_blocks_logout(
        self,
        client: AsyncClient,
        mock_settings: object,  # noqa: ARG002
        reset_active_session: None,
    ) -> None:
        photos_router._active_session_id = "fake-running"
        response = await client.post("/api/photos/auth/logout")
        assert response.status_code == 409
        del reset_active_session

    @pytest.mark.asyncio
    async def test_resume_unknown_session_returns_404(
        self,
        client: AsyncClient,
        mock_settings: object,  # noqa: ARG002
        reset_active_session: None,  # noqa: ARG002
    ) -> None:
        response = await client.post("/api/photos/sessions/missing/resume")
        assert response.status_code == 404
