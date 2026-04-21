"""Photo management API router."""

import asyncio
import logging
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationInfo, field_validator

from app.models.photo import DryRunResult
from app.models.state import DeletionState, DeletionStatus
from app.routers.accounts import get_browser_manager
from app.services.photo_service import PhotoService
from app.services.state_service import StateService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/photos", tags=["photos"])


# ---------------------------------------------------------------------------
# Concurrency guard
#
# ``BrowserManager`` is backed by a single Playwright persistent context,
# so a background deletion and anything that touches the browser (another
# deletion, dry-run, account switch, logout) cannot coexist. We enforce
# that invariant here with a single ``_active_session_id`` slot protected
# by an ``asyncio.Lock``. Handlers that would touch the shared browser
# take the lock, check the slot, and either claim it (for deletion /
# resume) or reject the request with 409 Conflict.
#
# All state is in-process and ephemeral. A server restart drops all
# slots; ``_recover_stale_in_progress_states`` downgrades any leftover
# ``in_progress`` states on disk to ``interrupted`` so the user can
# resume them.
# ---------------------------------------------------------------------------
_active_session_lock: asyncio.Lock = asyncio.Lock()
_active_session_id: str | None = None
_active_tasks: dict[str, asyncio.Task[object]] = {}
_cancellation_events: dict[str, asyncio.Event] = {}

# HTTP status for "another deletion is already running"
_CONFLICT_MESSAGE = (
    "削除セッションを実行中のため、この操作はできません。"
    "完了まで待つか、中断してから再度実行してください。"
)


def is_session_active() -> bool:
    """Whether any deletion session currently holds the browser."""
    return _active_session_id is not None


def active_session_id() -> str | None:
    """Return the id of the currently active deletion session, if any."""
    return _active_session_id


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
    """Response model for session information.

    Includes final result fields (``deleted_count`` / ``failed_count`` /
    ``failed_photo_ids``) so polling clients can reconstruct the
    completion message without needing a separate completion response.
    """

    session_id: str
    start_date: str
    end_date: str
    total_count: int
    processed_count: int
    status: str
    progress_percentage: float
    deleted_count: int = 0
    failed_count: int = 0
    failed_photo_ids: list[str] = Field(default_factory=list)


class SessionStartResponse(BaseModel):
    """Response returned by async deletion / resume endpoints.

    Only carries the identifiers the frontend needs to start polling.
    """

    session_id: str
    status: str


def _state_to_response(state: DeletionState) -> SessionResponse:
    return SessionResponse(
        session_id=state.session_id,
        start_date=state.start_date.isoformat(),
        end_date=state.end_date.isoformat(),
        total_count=state.total_count,
        processed_count=state.processed_count,
        status=state.status,
        progress_percentage=state.progress_percentage,
        deleted_count=state.deleted_count,
        failed_count=state.failed_count,
        failed_photo_ids=list(state.failed_photo_ids),
    )


async def _claim_session_slot(session_id: str) -> None:
    """Attempt to claim the single deletion slot. Raise 409 on conflict."""
    global _active_session_id  # noqa: PLW0603
    async with _active_session_lock:
        if _active_session_id is not None:
            raise HTTPException(status_code=409, detail=_CONFLICT_MESSAGE)
        _active_session_id = session_id


async def _release_session_slot(session_id: str) -> None:
    """Release the deletion slot if we still hold it."""
    global _active_session_id  # noqa: PLW0603
    async with _active_session_lock:
        if _active_session_id == session_id:
            _active_session_id = None
        _active_tasks.pop(session_id, None)
        _cancellation_events.pop(session_id, None)


async def _ensure_no_active_session() -> None:
    """For endpoints that share the browser but don't claim a slot."""
    async with _active_session_lock:
        if _active_session_id is not None:
            raise HTTPException(status_code=409, detail=_CONFLICT_MESSAGE)


async def recover_stale_in_progress_states() -> None:
    """Downgrade any ``in_progress`` state left on disk to ``interrupted``.

    Called once at app startup. Without this, a crash or unclean restart
    would leave state files flagged ``in_progress`` forever, and the UI
    would see them as neither resumable nor completed.
    """
    state_service = StateService()
    for session_id in await state_service.list_sessions():
        state = await state_service.load(session_id)
        if state and state.status == DeletionStatus.IN_PROGRESS:
            logger.info(
                "Recovering stale in_progress session %s as interrupted",
                session_id,
            )
            state.mark_interrupted()
            await state_service.save(state)


async def _run_deletion_task(
    *,
    session_id: str,
    start_date: date,
    end_date: date,
    expected_total: int | None,
    state: DeletionState,
    cancel_event: asyncio.Event,
) -> None:
    """Background coroutine: run the streaming deleter, always release slot."""
    try:
        mgr = get_browser_manager()
        client = await mgr.get_client()
        service = PhotoService(client)
        await service.delete_photos(
            start_date,
            end_date,
            dry_run=False,
            confirmed=True,
            expected_total=expected_total,
            state=state,
            cancel_event=cancel_event,
        )
    except Exception as e:  # noqa: BLE001 — log and persist, don't crash
        logger.exception("Deletion task %s failed: %s", session_id, e)
        state.mark_interrupted()
        await StateService().save(state)
    finally:
        await _release_session_slot(session_id)


async def _run_resume_task(
    *,
    session_id: str,
    cancel_event: asyncio.Event,
) -> None:
    """Background coroutine: resume an interrupted session."""
    try:
        mgr = get_browser_manager()
        client = await mgr.get_client()
        service = PhotoService(client)
        await service.resume_deletion(session_id, cancel_event=cancel_event)
    except Exception as e:  # noqa: BLE001
        logger.exception("Resume task %s failed: %s", session_id, e)
        state_service = StateService()
        state = await state_service.load(session_id)
        if state is not None:
            state.mark_interrupted()
            await state_service.save(state)
    finally:
        await _release_session_slot(session_id)


@router.post("/dry-run", response_model=DryRunResult)
async def dry_run(request: DateRangeRequest) -> DryRunResult:
    """Perform a dry run to count photos that would be deleted.

    Shares the browser with active deletion sessions, so it is rejected
    with 409 while a session is running.
    """
    await _ensure_no_active_session()

    mgr = get_browser_manager()
    client = await mgr.get_client()
    service = PhotoService(client)
    return await service.dry_run(request.start_date, request.end_date)


@router.post("/delete", response_model=SessionStartResponse)
async def delete_photos(request: DeleteRequest) -> SessionStartResponse:
    """Schedule a deletion run and return immediately.

    The streaming deleter runs in an ``asyncio`` background task. Use
    ``GET /api/photos/sessions/{session_id}`` to poll progress and
    ``POST /api/photos/sessions/{session_id}/interrupt`` to stop it.
    """
    if not request.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Deletion requires confirmation. Set confirmed=True.",
        )

    # Create the state (and therefore session_id) before scheduling, so
    # the response can reference it and the frontend can start polling
    # right away. Persist only after the slot is claimed, so a 409
    # doesn't leave orphaned session files on disk.
    state = DeletionState(
        start_date=request.start_date,
        end_date=request.end_date,
        total_count=request.expected_total or 0,
    )
    await _claim_session_slot(state.session_id)
    state.mark_in_progress()
    await StateService().save(state)

    cancel_event = asyncio.Event()
    _cancellation_events[state.session_id] = cancel_event

    task = asyncio.create_task(
        _run_deletion_task(
            session_id=state.session_id,
            start_date=request.start_date,
            end_date=request.end_date,
            expected_total=request.expected_total,
            state=state,
            cancel_event=cancel_event,
        ),
        name=f"delete-{state.session_id}",
    )
    _active_tasks[state.session_id] = task

    return SessionStartResponse(session_id=state.session_id, status=state.status)


@router.get("/sessions/interrupted", response_model=SessionResponse | None)
async def get_interrupted_session() -> SessionResponse | None:
    """Get any interrupted deletion session."""
    state_service = StateService()
    state = await state_service.find_interrupted()
    if state is None:
        return None
    return _state_to_response(state)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    """Poll a deletion session's state.

    Used by the frontend to render live progress while a deletion runs
    in the background.
    """
    state = await StateService().load(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return _state_to_response(state)


@router.post(
    "/sessions/{session_id}/interrupt",
    response_model=SessionResponse,
)
async def interrupt_session(session_id: str) -> SessionResponse:
    """Signal the running deletion task to stop at the next checkpoint.

    Returns the session's current state. The 200 response only confirms
    the signal was delivered — the task may take up to one UI step to
    actually stop. Clients should continue polling until ``status``
    becomes ``interrupted`` (or ``completed`` if the task finished
    before the signal landed).
    """
    state = await StateService().load(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    event = _cancellation_events.get(session_id)
    if event is not None:
        event.set()
    else:
        # No live task (server restart between delete start and interrupt).
        # Flip the persisted state so the frontend can resume.
        if state.status == DeletionStatus.IN_PROGRESS:
            state.mark_interrupted()
            await StateService().save(state)

    return _state_to_response(state)


@router.post("/sessions/{session_id}/resume", response_model=SessionStartResponse)
async def resume_session(session_id: str) -> SessionStartResponse:
    """Resume an interrupted deletion session (async)."""
    state_service = StateService()
    state = await state_service.load(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    if not state.is_resumable:
        raise HTTPException(
            status_code=400,
            detail=f"Session is not resumable (status: {state.status})",
        )

    await _claim_session_slot(session_id)

    # Persist the in_progress transition BEFORE scheduling the background
    # task. The polling client treats ``interrupted`` as terminal, so if
    # the first poll lands before the background coroutine flips the
    # status it would stop the UI flow even though resume is actually
    # running. Same pattern as the delete endpoint.
    state.mark_in_progress()
    await state_service.save(state)

    cancel_event = asyncio.Event()
    _cancellation_events[session_id] = cancel_event

    task = asyncio.create_task(
        _run_resume_task(session_id=session_id, cancel_event=cancel_event),
        name=f"resume-{session_id}",
    )
    _active_tasks[session_id] = task

    return SessionStartResponse(session_id=session_id, status=state.status)


@router.delete("/sessions/{session_id}")
async def cancel_session(session_id: str) -> dict[str, bool]:
    """Cancel and delete a session."""
    if _active_session_id == session_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot delete the state of an active session. Interrupt it first."
            ),
        )

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
    """Check authentication status for the active account."""
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

    await _ensure_no_active_session()

    svc = get_account_service()
    active = svc.get_active_account()
    if active is None:
        active = svc.create_account()

    return await login_account(active.account_id)


@router.post("/auth/logout")
async def logout() -> dict[str, bool]:
    """Logout the active account."""
    from app.routers.accounts import get_account_service, logout_account

    await _ensure_no_active_session()

    svc = get_account_service()
    active = svc.get_active_account()
    if active is None:
        return {"success": True}

    return await logout_account(active.account_id)
