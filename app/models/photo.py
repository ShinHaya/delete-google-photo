"""Photo model definitions."""

from datetime import datetime

from pydantic import BaseModel, Field


class Photo(BaseModel):
    """Represents a photo in Google Photos."""

    id: str = Field(..., description="Unique identifier of the photo")
    filename: str | None = Field(None, description="Original filename")
    created_at: datetime | None = Field(None, description="Photo creation timestamp")
    url: str | None = Field(None, description="URL to the photo in Google Photos")

    model_config = {"frozen": True}


class PhotoSummary(BaseModel):
    """Summary of photos for a specific date."""

    date: str = Field(..., description="Date in YYYY-MM-DD format")
    count: int = Field(..., ge=0, description="Number of photos on this date")


class DryRunResult(BaseModel):
    """Result of a dry run operation."""

    start_date: str = Field(..., description="Start date of the range")
    end_date: str = Field(..., description="End date of the range")
    total_count: int = Field(..., ge=0, description="Total number of photos to delete")
    photos_by_date: list[PhotoSummary] = Field(
        default_factory=list, description="Photo count per date"
    )


class DeletionResult(BaseModel):
    """Result of a deletion operation."""

    mode: str = Field(..., description="Operation mode: dry_run or delete")
    target_count: int = Field(..., ge=0, description="Number of photos targeted")
    deleted_count: int = Field(..., ge=0, description="Number of photos deleted")
    failed_count: int = Field(0, ge=0, description="Number of failed deletions")
    failed_photo_ids: list[str] = Field(
        default_factory=list, description="IDs of photos that failed to delete"
    )
