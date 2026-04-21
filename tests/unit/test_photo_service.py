"""Unit tests for PhotoService."""

import asyncio
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import DeletionCancelledError, InvalidDateRangeError
from app.models.state import DeletionState, DeletionStatus
from app.services.photo_service import PhotoService
from app.services.state_service import StateService


class TestPhotoService:
    """Tests for PhotoService."""

    @pytest.fixture
    def mock_browser_client(self) -> MagicMock:
        """Create a mock browser client."""
        client = MagicMock()
        client.is_logged_in = AsyncMock(return_value=True)
        client.page = MagicMock()
        return client

    @pytest.fixture
    def state_service(self, temp_dir: Path) -> StateService:
        """Create a state service with temporary directory."""
        return StateService(state_dir=temp_dir)

    @pytest.fixture
    def photo_service(
        self, mock_browser_client: MagicMock, state_service: StateService
    ) -> PhotoService:
        """Create a photo service with mocked dependencies."""
        return PhotoService(
            browser_client=mock_browser_client,
            state_service=state_service,
        )

    # Date validation tests

    def test_validate_date_range_valid(self, photo_service: PhotoService) -> None:
        """Test valid date range passes validation."""
        # Should not raise
        photo_service._validate_date_range(
            date(2020, 1, 1),
            date(2020, 12, 31),
        )

    def test_validate_date_range_same_date(self, photo_service: PhotoService) -> None:
        """Test same start and end date is valid."""
        photo_service._validate_date_range(
            date(2020, 6, 15),
            date(2020, 6, 15),
        )

    def test_validate_date_range_end_before_start(
        self, photo_service: PhotoService
    ) -> None:
        """Test end date before start date raises error."""
        with pytest.raises(InvalidDateRangeError, match="cannot be before"):
            photo_service._validate_date_range(
                date(2020, 12, 31),
                date(2020, 1, 1),
            )

    def test_validate_date_range_too_old(self, photo_service: PhotoService) -> None:
        """Test date before 2000 raises error."""
        with pytest.raises(InvalidDateRangeError, match="2000 or later"):
            photo_service._validate_date_range(
                date(1999, 12, 31),
                date(2000, 1, 1),
            )

    def test_validate_date_range_future(self, photo_service: PhotoService) -> None:
        """Test future date raises error."""
        with pytest.raises(InvalidDateRangeError, match="future"):
            photo_service._validate_date_range(
                date(2020, 1, 1),
                date(2099, 12, 31),
            )

    # Authentication tests

    @pytest.mark.asyncio
    async def test_ensure_authenticated_already_logged_in(
        self, photo_service: PhotoService, mock_browser_client: MagicMock
    ) -> None:
        """Test authentication when already logged in."""
        mock_browser_client.is_logged_in = AsyncMock(return_value=True)

        result = await photo_service.ensure_authenticated()

        assert result is True

    @pytest.mark.asyncio
    async def test_ensure_authenticated_needs_login(
        self, photo_service: PhotoService, mock_browser_client: MagicMock
    ) -> None:
        """Test authentication prompts for login when not logged in."""
        # First call returns False (not logged in), subsequent calls return True
        mock_browser_client.is_logged_in = AsyncMock(side_effect=[False, True])

        with patch.object(
            photo_service.auth,
            "wait_for_manual_login",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await photo_service.ensure_authenticated()
            assert result is True

    # Dry run tests

    @pytest.mark.asyncio
    async def test_dry_run_success(self, photo_service: PhotoService) -> None:
        """Test successful dry run."""
        from app.models.photo import PhotoSummary

        with patch.object(
            photo_service.operations,
            "get_photo_summary_by_date",
            new_callable=AsyncMock,
            return_value=[
                PhotoSummary(date="2020-01-01", count=50),
                PhotoSummary(date="2020-01-02", count=30),
            ],
        ):
            result = await photo_service.dry_run(
                date(2020, 1, 1),
                date(2020, 1, 31),
            )

        assert result.start_date == "2020-01-01"
        assert result.end_date == "2020-01-31"
        assert result.total_count == 80
        assert len(result.photos_by_date) == 2

    @pytest.mark.asyncio
    async def test_dry_run_invalid_date_range(
        self, photo_service: PhotoService
    ) -> None:
        """Test dry run with invalid date range."""
        with pytest.raises(InvalidDateRangeError):
            await photo_service.dry_run(
                date(2020, 12, 31),
                date(2020, 1, 1),
            )

    # Delete photos tests

    @pytest.mark.asyncio
    async def test_delete_photos_dry_run_mode(
        self, photo_service: PhotoService
    ) -> None:
        """Test delete_photos in dry run mode doesn't delete."""
        from app.models.photo import PhotoSummary

        with patch.object(
            photo_service.operations,
            "get_photo_summary_by_date",
            new_callable=AsyncMock,
            return_value=[PhotoSummary(date="2020-01-01", count=10)],
        ):
            result = await photo_service.delete_photos(
                date(2020, 1, 1),
                date(2020, 1, 31),
                dry_run=True,
            )

        assert result.mode == "dry_run"
        assert result.target_count == 10
        assert result.deleted_count == 0

    @pytest.mark.asyncio
    async def test_delete_photos_without_confirmation(
        self, photo_service: PhotoService
    ) -> None:
        """Test delete_photos without confirmation raises error."""
        with pytest.raises(ValueError, match="confirmation"):
            await photo_service.delete_photos(
                date(2020, 1, 1),
                date(2020, 1, 31),
                dry_run=False,
                confirmed=False,
            )

    @pytest.mark.asyncio
    async def test_delete_photos_with_confirmation(
        self, photo_service: PhotoService
    ) -> None:
        """Test delete_photos with confirmation deletes photos."""

        async def mock_streaming(
            *_args: object, **kwargs: object
        ) -> tuple[int, list[str]]:
            on_deleted = kwargs.get("on_photo_deleted")
            on_prog = kwargs.get("on_progress")
            for i in range(3):
                if on_deleted is not None:
                    await on_deleted(f"photo_{i}")  # type: ignore[operator]
                if on_prog is not None:
                    await on_prog(i + 1, 3, f"photo_{i}")  # type: ignore[operator]
            return 3, []

        with (
            patch.object(
                photo_service.operations,
                "count_photos_in_range",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch.object(
                photo_service.operations,
                "delete_photos_in_range_streaming",
                side_effect=mock_streaming,
            ) as mock_stream,
        ):
            result = await photo_service.delete_photos(
                date(2020, 1, 1),
                date(2020, 1, 31),
                dry_run=False,
                confirmed=True,
            )

        assert result.mode == "delete"
        assert result.target_count == 3
        assert result.deleted_count == 3
        assert result.failed_count == 0
        assert mock_stream.call_count == 1

    @pytest.mark.asyncio
    async def test_delete_photos_with_failures(
        self, photo_service: PhotoService
    ) -> None:
        """Test delete_photos handles failures gracefully."""

        async def mock_streaming(
            *_args: object, **kwargs: object
        ) -> tuple[int, list[str]]:
            on_deleted = kwargs.get("on_photo_deleted")
            on_prog = kwargs.get("on_progress")
            # 2 successes, 1 failure
            for i in (0, 2):
                if on_deleted is not None:
                    await on_deleted(f"photo_{i}")  # type: ignore[operator]
                if on_prog is not None:
                    await on_prog(i + 1, 3, f"photo_{i}")  # type: ignore[operator]
            return 2, ["photo_1"]

        with (
            patch.object(
                photo_service.operations,
                "count_photos_in_range",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch.object(
                photo_service.operations,
                "delete_photos_in_range_streaming",
                side_effect=mock_streaming,
            ),
        ):
            result = await photo_service.delete_photos(
                date(2020, 1, 1),
                date(2020, 1, 31),
                dry_run=False,
                confirmed=True,
            )

        assert result.deleted_count == 2
        assert result.failed_count == 1
        assert "photo_1" in result.failed_photo_ids

    @pytest.mark.asyncio
    async def test_delete_photos_empty_range(self, photo_service: PhotoService) -> None:
        """Test delete_photos with no photos in range."""
        with (
            patch.object(
                photo_service.operations,
                "count_photos_in_range",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch.object(
                photo_service.operations,
                "delete_photos_in_range_streaming",
                new_callable=AsyncMock,
            ) as mock_stream,
        ):
            result = await photo_service.delete_photos(
                date(2020, 1, 1),
                date(2020, 1, 31),
                dry_run=False,
                confirmed=True,
            )

        assert result.target_count == 0
        assert result.deleted_count == 0
        # Empty range must not invoke the streaming deleter.
        assert mock_stream.call_count == 0

    # Interrupted session tests

    @pytest.mark.asyncio
    async def test_get_interrupted_session(
        self, photo_service: PhotoService, state_service: StateService
    ) -> None:
        """Test getting an interrupted session."""
        interrupted_state = DeletionState(
            session_id="interrupted-123",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
            processed_count=50,
            status=DeletionStatus.INTERRUPTED,
        )
        await state_service.save(interrupted_state)

        result = await photo_service.get_interrupted_session()

        assert result is not None
        assert result.session_id == "interrupted-123"

    @pytest.mark.asyncio
    async def test_get_interrupted_session_none(
        self, photo_service: PhotoService
    ) -> None:
        """Test getting interrupted session when none exists."""
        result = await photo_service.get_interrupted_session()
        assert result is None

    @pytest.mark.asyncio
    async def test_cancel_session(
        self, photo_service: PhotoService, state_service: StateService
    ) -> None:
        """Test canceling a session."""
        state = DeletionState(
            session_id="to-cancel",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
        )
        await state_service.save(state)

        result = await photo_service.cancel_session("to-cancel")

        assert result is True
        assert await state_service.load("to-cancel") is None

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_session(
        self, photo_service: PhotoService
    ) -> None:
        """Test canceling a session that doesn't exist."""
        result = await photo_service.cancel_session("nonexistent")
        assert result is False

    # Resume tests

    @pytest.mark.asyncio
    async def test_resume_deletion_session_not_found(
        self, photo_service: PhotoService
    ) -> None:
        """Test resuming a nonexistent session raises error."""
        with pytest.raises(ValueError, match="Session not found"):
            await photo_service.resume_deletion("nonexistent")

    @pytest.mark.asyncio
    async def test_resume_deletion_not_resumable(
        self, photo_service: PhotoService, state_service: StateService
    ) -> None:
        """Test resuming a non-resumable session raises error."""
        completed_state = DeletionState(
            session_id="completed",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
            status=DeletionStatus.COMPLETED,
        )
        await state_service.save(completed_state)

        with pytest.raises(ValueError, match="not resumable"):
            await photo_service.resume_deletion("completed")

    # Cancellation tests

    @pytest.mark.asyncio
    async def test_delete_photos_cancel_event_marks_interrupted(
        self, photo_service: PhotoService, state_service: StateService
    ) -> None:
        """A cancel_event raised mid-run leaves state INTERRUPTED + resumable."""
        cancel_event = asyncio.Event()

        async def mock_streaming(
            *_args: object, **kwargs: object
        ) -> tuple[int, list[str]]:
            on_deleted = kwargs.get("on_photo_deleted")
            # Delete two photos, then trip the cancel signal. The service
            # bumps deleted_count first and only then checks cancel_event,
            # so both photos are counted before the next callback raises.
            assert on_deleted is not None
            await on_deleted("photo_0")  # type: ignore[operator]
            await on_deleted("photo_1")  # type: ignore[operator]
            cancel_event.set()
            await on_deleted("photo_2")  # type: ignore[operator]  # raises
            pytest.fail("on_photo_deleted should have raised after cancel")

        with (
            patch.object(
                photo_service.operations,
                "count_photos_in_range",
                new_callable=AsyncMock,
                return_value=10,
            ),
            patch.object(
                photo_service.operations,
                "delete_photos_in_range_streaming",
                side_effect=mock_streaming,
            ),
        ):
            result = await photo_service.delete_photos(
                date(2020, 1, 1),
                date(2020, 1, 31),
                dry_run=False,
                confirmed=True,
                cancel_event=cancel_event,
            )

        # The DeletionResult reflects partial progress (3rd photo was
        # intercepted before it could be counted, the first 2 completed).
        assert result.deleted_count == 3  # photo_2 was still counted before cancel check
        assert result.target_count == 10

        # The persisted state is resumable.
        sessions = await state_service.list_sessions()
        assert len(sessions) == 1
        state = await state_service.load(sessions[0])
        assert state is not None
        assert state.status == DeletionStatus.INTERRUPTED
        assert state.is_resumable
        assert state.deleted_count == 3

    @pytest.mark.asyncio
    async def test_delete_photos_persists_final_result_counts(
        self, photo_service: PhotoService, state_service: StateService
    ) -> None:
        """On completion, state must hold deleted_count + failed_photo_ids."""

        async def mock_streaming(
            *_args: object, **kwargs: object
        ) -> tuple[int, list[str]]:
            on_deleted = kwargs.get("on_photo_deleted")
            assert on_deleted is not None
            await on_deleted("photo_0")  # type: ignore[operator]
            return 1, ["photo_failed"]

        with (
            patch.object(
                photo_service.operations,
                "count_photos_in_range",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch.object(
                photo_service.operations,
                "delete_photos_in_range_streaming",
                side_effect=mock_streaming,
            ),
        ):
            await photo_service.delete_photos(
                date(2020, 1, 1),
                date(2020, 1, 31),
                dry_run=False,
                confirmed=True,
            )

        sessions = await state_service.list_sessions()
        assert len(sessions) == 1
        state = await state_service.load(sessions[0])
        assert state is not None
        assert state.status == DeletionStatus.COMPLETED
        assert state.deleted_count == 1
        assert state.failed_photo_ids == ["photo_failed"]
        assert state.failed_count == 1

    @pytest.mark.asyncio
    async def test_delete_photos_persists_failed_ids_before_interrupt(
        self, photo_service: PhotoService, state_service: StateService
    ) -> None:
        """Failed ids must survive a cancel that lands before the run returns."""
        cancel_event = asyncio.Event()

        async def mock_streaming(
            *_args: object, **kwargs: object
        ) -> tuple[int, list[str]]:
            on_failed = kwargs.get("on_photos_failed")
            assert on_failed is not None
            await on_failed(["photo_failed"])
            cancel_event.set()
            raise DeletionCancelledError("cancel after persisting failures")

        with (
            patch.object(
                photo_service.operations,
                "count_photos_in_range",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch.object(
                photo_service.operations,
                "delete_photos_in_range_streaming",
                side_effect=mock_streaming,
            ),
        ):
            result = await photo_service.delete_photos(
                date(2020, 1, 1),
                date(2020, 1, 31),
                dry_run=False,
                confirmed=True,
                cancel_event=cancel_event,
            )

        assert result.deleted_count == 0
        assert result.failed_count == 1
        assert result.failed_photo_ids == ["photo_failed"]

        sessions = await state_service.list_sessions()
        assert len(sessions) == 1
        state = await state_service.load(sessions[0])
        assert state is not None
        assert state.status == DeletionStatus.INTERRUPTED
        assert state.failed_count == 1
        assert state.failed_photo_ids == ["photo_failed"]
