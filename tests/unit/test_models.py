"""Unit tests for data models."""

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from app.models.photo import DeletionResult, DryRunResult, Photo, PhotoSummary
from app.models.state import DeletionState, DeletionStatus


class TestPhoto:
    """Tests for Photo model."""

    def test_create_photo(self) -> None:
        """Test creating a photo with all fields."""
        photo = Photo(
            id="photo_123",
            filename="IMG_001.jpg",
            created_at=datetime(2020, 6, 15, 10, 30, 0),
            url="https://photos.google.com/photo/123",
        )
        assert photo.id == "photo_123"
        assert photo.filename == "IMG_001.jpg"
        assert photo.created_at == datetime(2020, 6, 15, 10, 30, 0)
        assert photo.url == "https://photos.google.com/photo/123"

    def test_create_photo_minimal(self) -> None:
        """Test creating a photo with only required fields."""
        photo = Photo(id="photo_123")
        assert photo.id == "photo_123"
        assert photo.filename is None
        assert photo.created_at is None
        assert photo.url is None

    def test_photo_is_frozen(self) -> None:
        """Test that Photo is immutable."""
        photo = Photo(id="photo_123")
        with pytest.raises(ValidationError):
            photo.id = "new_id"  # type: ignore[misc]


class TestPhotoSummary:
    """Tests for PhotoSummary model."""

    def test_create_summary(self) -> None:
        """Test creating a photo summary."""
        summary = PhotoSummary(date="2020-06-15", count=45)
        assert summary.date == "2020-06-15"
        assert summary.count == 45

    def test_count_must_be_non_negative(self) -> None:
        """Test that count cannot be negative."""
        with pytest.raises(ValueError):
            PhotoSummary(date="2020-06-15", count=-1)


class TestDryRunResult:
    """Tests for DryRunResult model."""

    def test_create_dry_run_result(self) -> None:
        """Test creating a dry run result."""
        result = DryRunResult(
            start_date="2020-01-01",
            end_date="2020-12-31",
            total_count=100,
            photos_by_date=[
                PhotoSummary(date="2020-01-01", count=45),
                PhotoSummary(date="2020-01-02", count=55),
            ],
        )
        assert result.start_date == "2020-01-01"
        assert result.end_date == "2020-12-31"
        assert result.total_count == 100
        assert len(result.photos_by_date) == 2


class TestDeletionResult:
    """Tests for DeletionResult model."""

    def test_create_deletion_result(self) -> None:
        """Test creating a deletion result."""
        result = DeletionResult(
            mode="dry_run",
            target_count=100,
            deleted_count=0,
        )
        assert result.mode == "dry_run"
        assert result.target_count == 100
        assert result.deleted_count == 0
        assert result.failed_count == 0
        assert result.failed_photo_ids == []

    def test_deletion_result_with_failures(self) -> None:
        """Test deletion result with failed photos."""
        result = DeletionResult(
            mode="delete",
            target_count=100,
            deleted_count=95,
            failed_count=5,
            failed_photo_ids=["p1", "p2", "p3", "p4", "p5"],
        )
        assert result.failed_count == 5
        assert len(result.failed_photo_ids) == 5


class TestDeletionState:
    """Tests for DeletionState model."""

    def test_create_state(self) -> None:
        """Test creating a deletion state."""
        state = DeletionState(
            session_id="test-session",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
            processed_count=0,
        )
        assert state.session_id == "test-session"
        assert state.start_date == date(2020, 1, 1)
        assert state.end_date == date(2020, 12, 31)
        assert state.total_count == 100
        assert state.processed_count == 0
        assert state.status == DeletionStatus.PENDING

    def test_create_state_with_string_dates(self) -> None:
        """Test creating a state with string dates."""
        state = DeletionState(
            session_id="test-session",
            start_date="2020-01-01",
            end_date="2020-12-31",
            total_count=100,
        )
        assert state.start_date == date(2020, 1, 1)
        assert state.end_date == date(2020, 12, 31)

    def test_progress_percentage_zero(self) -> None:
        """Test progress calculation when no photos processed."""
        state = DeletionState(
            session_id="test-session",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
            processed_count=0,
        )
        assert state.progress_percentage == 0.0

    def test_progress_percentage_half(self) -> None:
        """Test progress calculation at 50%."""
        state = DeletionState(
            session_id="test-session",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
            processed_count=50,
        )
        assert state.progress_percentage == 50.0

    def test_progress_percentage_complete(self) -> None:
        """Test progress calculation at 100%."""
        state = DeletionState(
            session_id="test-session",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
            processed_count=100,
        )
        assert state.progress_percentage == 100.0

    def test_progress_percentage_empty_total(self) -> None:
        """Test progress calculation when total is zero."""
        state = DeletionState(
            session_id="test-session",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=0,
            processed_count=0,
        )
        assert state.progress_percentage == 0.0

    def test_invalid_date_range(self) -> None:
        """Test that end_date before start_date raises error."""
        with pytest.raises(ValueError, match="end_date must be on or after start_date"):
            DeletionState(
                session_id="test-session",
                start_date=date(2020, 12, 31),
                end_date=date(2020, 1, 1),
                total_count=100,
            )

    def test_processed_count_exceeds_total(self) -> None:
        """Test that processed_count exceeding total raises error."""
        with pytest.raises(
            ValueError, match="processed_count cannot exceed total_count"
        ):
            DeletionState(
                session_id="test-session",
                start_date=date(2020, 1, 1),
                end_date=date(2020, 12, 31),
                total_count=100,
                processed_count=150,
            )

    def test_increment_processed(self) -> None:
        """Test incrementing processed count."""
        state = DeletionState(
            session_id="test-session",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
            processed_count=0,
        )
        state.increment_processed("photo_1")
        assert state.processed_count == 1
        assert state.last_processed_id == "photo_1"

    def test_status_transitions(self) -> None:
        """Test status transition methods."""
        state = DeletionState(
            session_id="test-session",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
        )
        assert state.status == DeletionStatus.PENDING

        state.mark_in_progress()
        assert state.status == DeletionStatus.IN_PROGRESS

        state.mark_completed()
        assert state.status == DeletionStatus.COMPLETED
        assert state.is_complete

    def test_is_resumable(self) -> None:
        """Test is_resumable property."""
        state = DeletionState(
            session_id="test-session",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
        )
        assert not state.is_resumable

        state.mark_interrupted()
        assert state.is_resumable
