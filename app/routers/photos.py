"""Photo management API router."""

from datetime import date

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, ValidationInfo, field_validator

from app.models.photo import DeletionResult, DryRunResult
from app.models.state import DeletionState
from app.routers.accounts import get_browser_manager
from app.services.photo_service import PhotoService
from app.services.state_service import StateService

router = APIRouter(prefix="/api/photos", tags=["photos"])

# Global state for active deletion tasks
_active_sessions: dict[str, DeletionState] = {}


class DateRangeRequest(BaseModel):
    """Request model for date range operations."""

    start_date: date = Field(..., description="Start date of the range")
    end_date: date = Field(..., description="End date of the range")

    @field_validator("end_date")
    @classmethod
    def validate_date_range(cls, v: date, info: ValidationInfo) -> date:
        """Validate that end_date is not before start_date."""
        start = info.data.get("start_date")
        if start and v < start:
            raise ValueError("end_date must be on or after start_date")
        return v

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_reasonable_date(cls, v: date) -> date:
        """Validate date is within reasonable bounds."""
        if v.year < 2000:
            raise ValueError("Date must be 2000 or later")
        if v > date.today():
            raise ValueError("Date cannot be in the future")
        return v


class DeleteRequest(DateRangeRequest):
    """Request model for deletion operations."""

    confirmed: bool = Field(False, description="Must be True to actually delete photos")
    expected_total: int | None = Field(
        None,
        ge=0,
        description=(
            "Pre-computed photo count from a prior dry run. "
            "When provided, the backend skips the initial counting pass "
            "and uses this value for progress reporting."
        ),
    )


class SessionResponse(BaseModel):
    """Response model for session information."""

    session_id: str
    start_date: str
    end_date: str
    total_count: int
    processed_count: int
    status: str
    progress_percentage: float


@router.post("/dry-run", response_model=DryRunResult)
async def dry_run(request: DateRangeRequest) -> DryRunResult:
    """Perform a dry run to count photos that would be deleted.

    Args:
        request: Date range request

    Returns:
        DryRunResult with photo counts
    """
    mgr = get_browser_manager()
    client = await mgr.get_client()
    service = PhotoService(client)
    return await service.dry_run(request.start_date, request.end_date)


@router.post("/delete", response_model=DeletionResult)
async def delete_photos(
    request: DeleteRequest,
    _background_tasks: BackgroundTasks,
) -> DeletionResult:
    """Delete photos in a date range.

    Args:
        request: Delete request with date range and confirmation
        background_tasks: FastAPI background tasks

    Returns:
        DeletionResult with deletion statistics
    """
    if not request.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Deletion requires confirmation. Set confirmed=True.",
        )

    # For now, run synchronously
    # TODO: Implement async deletion with WebSocket progress updates
    mgr = get_browser_manager()
    client = await mgr.get_client()
    service = PhotoService(client)
    return await service.delete_photos(
        request.start_date,
        request.end_date,
        dry_run=False,
        confirmed=True,
        expected_total=request.expected_total,
    )


@router.get("/sessions/interrupted", response_model=SessionResponse | None)
async def get_interrupted_session() -> SessionResponse | None:
    """Get any interrupted deletion session.

    Returns:
        Session info if found, None otherwise
    """
    state_service = StateService()
    state = await state_service.find_interrupted()

    if state is None:
        return None

    return SessionResponse(
        session_id=state.session_id,
        start_date=state.start_date.isoformat(),
        end_date=state.end_date.isoformat(),
        total_count=state.total_count,
        processed_count=state.processed_count,
        status=state.status,
        progress_percentage=state.progress_percentage,
    )


@router.post("/sessions/{session_id}/resume", response_model=DeletionResult)
async def resume_session(session_id: str) -> DeletionResult:
    """Resume an interrupted deletion session.

    Args:
        session_id: Session ID to resume

    Returns:
        DeletionResult with deletion statistics
    """
    mgr = get_browser_manager()
    client = await mgr.get_client()
    service = PhotoService(client)
    try:
        return await service.resume_deletion(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/sessions/{session_id}")
async def cancel_session(session_id: str) -> dict[str, bool]:
    """Cancel and delete a session.

    Args:
        session_id: Session ID to cancel

    Returns:
        Success status
    """
    state_service = StateService()
    deleted = await state_service.delete(session_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {session_id}",
        )

    return {"deleted": True}


@router.get("/auth/status")
async def get_auth_status() -> dict[str, bool]:
    """Check authentication status for the active account.

    Returns:
        Authentication status
    """
    from app.routers.accounts import get_account_service

    svc = get_account_service()
    active = svc.get_active_account()
    if active is None:
        return {"authenticated": False}

    mgr = get_browser_manager()
    try:
        client = await mgr.get_client()
        is_logged_in = await client.is_logged_in()
        return {"authenticated": is_logged_in}
    except Exception:
        return {"authenticated": False}


@router.post("/auth/login")
async def login() -> dict[str, bool | str]:
    """Start login flow for the active account.

    If no account exists, creates one first.
    """
    from app.routers.accounts import get_account_service, login_account

    svc = get_account_service()
    active = svc.get_active_account()
    if active is None:
        # Auto-create first account
        active = svc.create_account()

    return await login_account(active.account_id)


@router.post("/auth/logout")
async def logout() -> dict[str, bool]:
    """Logout the active account."""
    from app.routers.accounts import get_account_service, logout_account

    svc = get_account_service()
    active = svc.get_active_account()
    if active is None:
        return {"success": True}

    return await logout_account(active.account_id)
