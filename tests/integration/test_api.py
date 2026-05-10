"""Integration tests for API endpoints."""

import asyncio
from collections.abc import Coroutine, Generator
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.exceptions import StateError
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
    async def test_concurrency_guard_blocks_account_create(
        self,
        client: AsyncClient,
        mock_settings: object,  # noqa: ARG002
        reset_active_session: None,
    ) -> None:
        """Creating a new account is blocked while a session is running."""
        photos_router._active_session_id = "fake-running"

        response = await client.post("/api/accounts")
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

    @pytest.mark.asyncio
    async def test_resume_persists_in_progress_before_background_task(
        self,
        client: AsyncClient,
        mock_settings: object,  # noqa: ARG002
        reset_active_session: None,  # noqa: ARG002
    ) -> None:
        state = DeletionState(
            session_id="resume-me",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 31),
            total_count=10,
            processed_count=4,
            deleted_count=4,
            status=DeletionStatus.INTERRUPTED,
        )
        await StateService().save(state)

        def fake_create_task(
            coro: Coroutine[Any, Any, None], *, name: str | None = None
        ) -> MagicMock:
            del name
            coro.close()
            return MagicMock(name="resume-task")

        with patch.object(
            photos_router.asyncio,
            "create_task",
            side_effect=fake_create_task,
        ):
            response = await client.post("/api/photos/sessions/resume-me/resume")

        assert response.status_code == 200
        data = response.json()
        assert data == {"session_id": "resume-me", "status": "in_progress"}

        persisted = await StateService().load("resume-me")
        assert persisted is not None
        assert persisted.status == DeletionStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_delete_releases_session_slot_when_state_save_fails(
        self,
        client: AsyncClient,
        mock_settings: object,  # noqa: ARG002
        reset_active_session: None,  # noqa: ARG002
    ) -> None:
        with (
            patch.object(
                StateService,
                "save",
                new=AsyncMock(side_effect=StateError("save failed")),
            ),
            pytest.raises(StateError, match="save failed"),
        ):
            await client.post(
                "/api/photos/delete",
                json={
                    "start_date": "2020-01-01",
                    "end_date": "2020-01-31",
                    "confirmed": True,
                },
            )

        assert photos_router._active_session_id is None
        assert photos_router._active_tasks == {}
        assert photos_router._cancellation_events == {}

        def fake_create_task(
            coro: Coroutine[Any, Any, None], *, name: str | None = None
        ) -> MagicMock:
            del name
            coro.close()
            return MagicMock(name="delete-task")

        with patch.object(
            photos_router.asyncio,
            "create_task",
            side_effect=fake_create_task,
        ):
            response = await client.post(
                "/api/photos/delete",
                json={
                    "start_date": "2020-01-01",
                    "end_date": "2020-01-31",
                    "confirmed": True,
                },
            )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_releases_session_slot_when_task_creation_fails(
        self,
        client: AsyncClient,
        mock_settings: object,  # noqa: ARG002
        reset_active_session: None,  # noqa: ARG002
    ) -> None:
        with (
            patch.object(
                photos_router.asyncio,
                "create_task",
                side_effect=RuntimeError("task setup failed"),
            ),
            pytest.raises(RuntimeError, match="task setup failed"),
        ):
            await client.post(
                "/api/photos/delete",
                json={
                    "start_date": "2020-01-01",
                    "end_date": "2020-01-31",
                    "confirmed": True,
                },
            )

        assert photos_router._active_session_id is None
        assert photos_router._active_tasks == {}
        assert photos_router._cancellation_events == {}

    @pytest.mark.asyncio
    async def test_delete_releases_session_slot_when_setup_is_cancelled(
        self,
        client: AsyncClient,
        mock_settings: object,  # noqa: ARG002
        reset_active_session: None,  # noqa: ARG002
    ) -> None:
        with (
            patch.object(
                StateService,
                "save",
                new=AsyncMock(side_effect=asyncio.CancelledError),
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await client.post(
                "/api/photos/delete",
                json={
                    "start_date": "2020-01-01",
                    "end_date": "2020-01-31",
                    "confirmed": True,
                },
            )

        assert photos_router._active_session_id is None
        assert photos_router._active_tasks == {}
        assert photos_router._cancellation_events == {}

    @pytest.mark.asyncio
    async def test_resume_releases_session_slot_when_state_save_fails(
        self,
        client: AsyncClient,
        mock_settings: object,  # noqa: ARG002
        reset_active_session: None,  # noqa: ARG002
    ) -> None:
        state = DeletionState(
            session_id="resume-save-fails",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 31),
            total_count=10,
            status=DeletionStatus.INTERRUPTED,
        )
        await StateService().save(state)

        with (
            patch.object(
                StateService,
                "save",
                new=AsyncMock(side_effect=StateError("save failed")),
            ),
            pytest.raises(StateError, match="save failed"),
        ):
            await client.post(
                "/api/photos/sessions/resume-save-fails/resume",
            )

        assert photos_router._active_session_id is None
        assert photos_router._active_tasks == {}
        assert photos_router._cancellation_events == {}

    @pytest.mark.asyncio
    async def test_resume_releases_session_slot_when_setup_is_cancelled(
        self,
        client: AsyncClient,
        mock_settings: object,  # noqa: ARG002
        reset_active_session: None,  # noqa: ARG002
    ) -> None:
        state = DeletionState(
            session_id="resume-cancelled",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 31),
            total_count=10,
            status=DeletionStatus.INTERRUPTED,
        )
        await StateService().save(state)

        with (
            patch.object(
                StateService,
                "save",
                new=AsyncMock(side_effect=asyncio.CancelledError),
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await client.post("/api/photos/sessions/resume-cancelled/resume")

        assert photos_router._active_session_id is None
        assert photos_router._active_tasks == {}
        assert photos_router._cancellation_events == {}

        persisted = await StateService().load("resume-cancelled")
        assert persisted is not None
        assert persisted.status == DeletionStatus.INTERRUPTED

        def fake_create_task(
            coro: Coroutine[Any, Any, None], *, name: str | None = None
        ) -> MagicMock:
            del name
            coro.close()
            return MagicMock(name="resume-task")

        with patch.object(
            photos_router.asyncio,
            "create_task",
            side_effect=fake_create_task,
        ):
            # The cancelled save was mocked, so the on-disk state is still resumable.
            response = await client.post(
                "/api/photos/sessions/resume-cancelled/resume",
            )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_resume_releases_session_slot_when_task_creation_fails(
        self,
        client: AsyncClient,
        mock_settings: object,  # noqa: ARG002
        reset_active_session: None,  # noqa: ARG002
    ) -> None:
        state = DeletionState(
            session_id="resume-task-fails",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 31),
            total_count=10,
            status=DeletionStatus.INTERRUPTED,
        )
        await StateService().save(state)

        with (
            patch.object(
                photos_router.asyncio,
                "create_task",
                side_effect=RuntimeError("task setup failed"),
            ),
            pytest.raises(RuntimeError, match="task setup failed"),
        ):
            await client.post("/api/photos/sessions/resume-task-fails/resume")

        assert photos_router._active_session_id is None
        assert photos_router._active_tasks == {}
        assert photos_router._cancellation_events == {}

        persisted = await StateService().load("resume-task-fails")
        assert persisted is not None
        assert persisted.status == DeletionStatus.INTERRUPTED
