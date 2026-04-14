"""State model for tracking deletion progress."""

from datetime import date, datetime
from enum import StrEnum
from typing import Self
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class DeletionStatus(StrEnum):
    """Status of a deletion session."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class DeletionState(BaseModel):
    """State of a deletion session for resume functionality."""

    session_id: str = Field(
        default_factory=lambda: str(uuid4()), description="Unique session identifier"
    )
    start_date: date = Field(..., description="Start date of the deletion range")
    end_date: date = Field(..., description="End date of the deletion range")
    total_count: int = Field(..., ge=0, description="Total number of photos to delete")
    processed_count: int = Field(
        0, ge=0, description="Number of photos processed so far"
    )
    last_processed_id: str | None = Field(
        None, description="ID of the last processed photo"
    )
    status: DeletionStatus = Field(
        DeletionStatus.PENDING, description="Current status of the deletion"
    )
    created_at: datetime = Field(
        default_factory=datetime.now, description="Session creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=datetime.now, description="Last update timestamp"
    )

    model_config = {"use_enum_values": True}

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def parse_date(cls, v: date | str) -> date:
        """Parse date from string if necessary."""
        if isinstance(v, str):
            return date.fromisoformat(v)
        return v

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        """Validate that end_date is not before start_date."""
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self

    @model_validator(mode="after")
    def validate_processed_count(self) -> Self:
        """Validate that processed_count does not exceed total_count."""
        if self.processed_count > self.total_count:
            raise ValueError("processed_count cannot exceed total_count")
        return self

    @property
    def progress_percentage(self) -> float:
        """Calculate progress as a percentage."""
        if self.total_count == 0:
            return 0.0
        return (self.processed_count / self.total_count) * 100.0

    @property
    def is_complete(self) -> bool:
        """Check if deletion is complete."""
        return self.status == DeletionStatus.COMPLETED

    @property
    def is_resumable(self) -> bool:
        """Check if this session can be resumed."""
        return self.status == DeletionStatus.INTERRUPTED

    def increment_processed(self, photo_id: str) -> None:
        """Increment processed count and update last processed ID."""
        self.processed_count += 1
        self.last_processed_id = photo_id
        self.updated_at = datetime.now()

    def mark_in_progress(self) -> None:
        """Mark the session as in progress."""
        self.status = DeletionStatus.IN_PROGRESS
        self.updated_at = datetime.now()

    def mark_completed(self) -> None:
        """Mark the session as completed."""
        self.status = DeletionStatus.COMPLETED
        self.updated_at = datetime.now()

    def mark_interrupted(self) -> None:
        """Mark the session as interrupted."""
        self.status = DeletionStatus.INTERRUPTED
        self.updated_at = datetime.now()

    def mark_failed(self) -> None:
        """Mark the session as failed."""
        self.status = DeletionStatus.FAILED
        self.updated_at = datetime.now()
