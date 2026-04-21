"""Unit tests for StateService."""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from app.exceptions import StateError
from app.models.state import DeletionState, DeletionStatus
from app.services.state_service import StateService


class TestStateService:
    """Tests for StateService."""

    @pytest.fixture
    def state_service(self, temp_dir: Path) -> StateService:
        """Create a state service with temporary directory."""
        return StateService(state_dir=temp_dir)

    @pytest.fixture
    def sample_state(self) -> DeletionState:
        """Create a sample deletion state."""
        return DeletionState(
            session_id="test-session-123",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
            processed_count=50,
            last_processed_id="photo_50",
            status=DeletionStatus.IN_PROGRESS,
        )

    @pytest.mark.asyncio
    async def test_save_and_load_state(
        self, state_service: StateService, sample_state: DeletionState
    ) -> None:
        """Test saving and loading state."""
        await state_service.save(sample_state)
        loaded = await state_service.load(sample_state.session_id)

        assert loaded is not None
        assert loaded.session_id == sample_state.session_id
        assert loaded.start_date == sample_state.start_date
        assert loaded.end_date == sample_state.end_date
        assert loaded.total_count == sample_state.total_count
        assert loaded.processed_count == sample_state.processed_count
        assert loaded.last_processed_id == sample_state.last_processed_id
        assert loaded.status == sample_state.status

    @pytest.mark.asyncio
    async def test_load_nonexistent_state(self, state_service: StateService) -> None:
        """Test loading a state that doesn't exist returns None."""
        loaded = await state_service.load("nonexistent-session")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_delete_state(
        self, state_service: StateService, sample_state: DeletionState
    ) -> None:
        """Test deleting a state."""
        await state_service.save(sample_state)

        # Verify it exists
        loaded = await state_service.load(sample_state.session_id)
        assert loaded is not None

        # Delete it
        deleted = await state_service.delete(sample_state.session_id)
        assert deleted is True

        # Verify it's gone
        loaded = await state_service.load(sample_state.session_id)
        assert loaded is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_state(self, state_service: StateService) -> None:
        """Test deleting a state that doesn't exist returns False."""
        deleted = await state_service.delete("nonexistent-session")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_list_sessions(
        self, state_service: StateService, sample_state: DeletionState
    ) -> None:
        """Test listing all sessions."""
        # Create multiple sessions
        state1 = sample_state
        state2 = DeletionState(
            session_id="test-session-456",
            start_date=date(2021, 1, 1),
            end_date=date(2021, 12, 31),
            total_count=200,
        )

        await state_service.save(state1)
        await state_service.save(state2)

        sessions = await state_service.list_sessions()

        assert len(sessions) == 2
        assert "test-session-123" in sessions
        assert "test-session-456" in sessions

    @pytest.mark.asyncio
    async def test_list_sessions_ignores_accounts_registry(
        self, state_service: StateService
    ) -> None:
        """Non-session JSON files in state_dir must be ignored."""
        accounts_file = state_service.state_dir / "accounts.json"
        accounts_file.write_text(
            json.dumps({"accounts": [], "active_account_id": None}),
            encoding="utf-8",
        )

        sessions = await state_service.list_sessions()

        assert sessions == []

    @pytest.mark.asyncio
    async def test_find_interrupted(self, state_service: StateService) -> None:
        """Test finding an interrupted session."""
        # Create a completed session
        completed_state = DeletionState(
            session_id="completed-session",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
            status=DeletionStatus.COMPLETED,
        )
        await state_service.save(completed_state)

        # Create an interrupted session
        interrupted_state = DeletionState(
            session_id="interrupted-session",
            start_date=date(2021, 1, 1),
            end_date=date(2021, 12, 31),
            total_count=200,
            processed_count=50,
            status=DeletionStatus.INTERRUPTED,
        )
        await state_service.save(interrupted_state)

        # Find interrupted
        found = await state_service.find_interrupted()

        assert found is not None
        assert found.session_id == "interrupted-session"
        assert found.status == DeletionStatus.INTERRUPTED

    @pytest.mark.asyncio
    async def test_find_interrupted_returns_most_recent_session(
        self, state_service: StateService
    ) -> None:
        older = DeletionState(
            session_id="older-interrupted",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 2),
            total_count=10,
            status=DeletionStatus.INTERRUPTED,
            updated_at=datetime.now() - timedelta(days=1),
        )
        newer = DeletionState(
            session_id="newer-interrupted",
            start_date=date(2015, 2, 24),
            end_date=date(2015, 2, 25),
            total_count=12,
            status=DeletionStatus.INTERRUPTED,
            updated_at=datetime.now(),
        )
        await state_service.save(older)
        await state_service.save(newer)

        found = await state_service.find_interrupted()

        assert found is not None
        assert found.session_id == "newer-interrupted"
        assert found.start_date == date(2015, 2, 24)
        assert found.end_date == date(2015, 2, 25)

    @pytest.mark.asyncio
    async def test_find_interrupted_none(self, state_service: StateService) -> None:
        """Test finding interrupted when none exists."""
        # Create only completed sessions
        completed_state = DeletionState(
            session_id="completed-session",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
            status=DeletionStatus.COMPLETED,
        )
        await state_service.save(completed_state)

        found = await state_service.find_interrupted()
        assert found is None

    @pytest.mark.asyncio
    async def test_find_in_progress(self, state_service: StateService) -> None:
        """Test finding an in-progress session."""
        in_progress_state = DeletionState(
            session_id="in-progress-session",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
            processed_count=25,
            status=DeletionStatus.IN_PROGRESS,
        )
        await state_service.save(in_progress_state)

        found = await state_service.find_in_progress()

        assert found is not None
        assert found.session_id == "in-progress-session"
        assert found.status == DeletionStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_find_interrupted_skips_invalid_non_session_json(
        self, state_service: StateService
    ) -> None:
        """Malformed / foreign JSON files must not break interrupted lookup."""
        accounts_file = state_service.state_dir / "accounts.json"
        accounts_file.write_text(
            json.dumps({"accounts": [{"account_id": "x"}]}),
            encoding="utf-8",
        )
        interrupted = DeletionState(
            session_id="real-interrupted",
            start_date=date(2015, 2, 24),
            end_date=date(2015, 2, 25),
            total_count=5,
            status=DeletionStatus.INTERRUPTED,
        )
        await state_service.save(interrupted)

        found = await state_service.find_interrupted()

        assert found is not None
        assert found.session_id == "real-interrupted"

    @pytest.mark.asyncio
    async def test_cleanup_completed(self, state_service: StateService) -> None:
        """Test cleaning up completed sessions."""
        # Create various sessions
        completed1 = DeletionState(
            session_id="completed-1",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
            status=DeletionStatus.COMPLETED,
        )
        completed2 = DeletionState(
            session_id="completed-2",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
            status=DeletionStatus.COMPLETED,
        )
        in_progress = DeletionState(
            session_id="in-progress",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
            status=DeletionStatus.IN_PROGRESS,
        )

        await state_service.save(completed1)
        await state_service.save(completed2)
        await state_service.save(in_progress)

        # Cleanup completed
        deleted_count = await state_service.cleanup_completed()

        assert deleted_count == 2

        # Verify only in-progress remains
        sessions = await state_service.list_sessions()
        assert len(sessions) == 1
        assert "in-progress" in sessions

    @pytest.mark.asyncio
    async def test_update_progress(
        self, state_service: StateService, sample_state: DeletionState
    ) -> None:
        """Test updating progress for a session."""
        await state_service.save(sample_state)

        updated = await state_service.update_progress(
            sample_state.session_id,
            processed_count=75,
            last_processed_id="photo_75",
        )

        assert updated is not None
        assert updated.processed_count == 75
        assert updated.last_processed_id == "photo_75"

        # Verify persisted
        loaded = await state_service.load(sample_state.session_id)
        assert loaded is not None
        assert loaded.processed_count == 75

    @pytest.mark.asyncio
    async def test_update_progress_nonexistent(
        self, state_service: StateService
    ) -> None:
        """Test updating progress for nonexistent session."""
        updated = await state_service.update_progress(
            "nonexistent",
            processed_count=50,
        )
        assert updated is None

    @pytest.mark.asyncio
    async def test_state_file_permissions(
        self, state_service: StateService, sample_state: DeletionState
    ) -> None:
        """Test that state files have restrictive permissions."""
        await state_service.save(sample_state)

        state_file = state_service._get_state_file(sample_state.session_id)
        # Check file exists and has owner-only permissions (0o600)
        assert state_file.exists()
        mode = state_file.stat().st_mode & 0o777
        assert mode == 0o600

    @pytest.mark.asyncio
    async def test_load_invalid_json(
        self, state_service: StateService, temp_dir: Path
    ) -> None:
        """Test loading an invalid JSON file raises StateError."""
        # Create invalid JSON file
        state_file = temp_dir / "invalid-session.json"
        state_file.write_text("not valid json {{{")

        with pytest.raises(StateError, match="Invalid state file format"):
            await state_service.load("invalid-session")

    @pytest.mark.asyncio
    async def test_state_directory_created(self, temp_dir: Path) -> None:
        """Test that state directory is created if it doesn't exist."""
        new_dir = temp_dir / "new_state_dir"
        assert not new_dir.exists()

        StateService(state_dir=new_dir)
        assert new_dir.exists()
