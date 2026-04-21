"""Photo service for managing photo deletion operations."""

import asyncio
import logging
from collections.abc import Callable
from datetime import date
from typing import Any

from app.browser.auth import GoogleAuthenticator
from app.browser.client import BrowserClient
from app.browser.operations import PhotoOperations
from app.exceptions import DeletionCancelledError, InvalidDateRangeError
from app.models.photo import DeletionResult, DryRunResult
from app.models.state import DeletionState
from app.services.state_service import StateService

logger = logging.getLogger(__name__)

# Type alias for progress callback
ProgressCallback = Callable[[int, int, str], Any]


class PhotoService:
    """High-level service for photo deletion operations."""

    def __init__(
        self,
        browser_client: BrowserClient,
        state_service: StateService | None = None,
    ) -> None:
        """Initialize photo service.

        Args:
            browser_client: Browser client instance
            state_service: Optional state service for persistence
        """
        self.client = browser_client
        self.auth = GoogleAuthenticator(browser_client)
        self.operations = PhotoOperations(browser_client)
        self.state_service = state_service or StateService()

    def _validate_date_range(self, start_date: date, end_date: date) -> None:
        """Validate date range.

        Args:
            start_date: Start date
            end_date: End date

        Raises:
            InvalidDateRangeError: If date range is invalid
        """
        if end_date < start_date:
            raise InvalidDateRangeError(
                f"End date ({end_date}) cannot be before start date ({start_date})"
            )

        if start_date.year < 2000:
            raise InvalidDateRangeError("Start date must be 2000 or later")

        if end_date > date.today():
            raise InvalidDateRangeError("End date cannot be in the future")

    async def ensure_authenticated(self, timeout: int = 300) -> bool:
        """Ensure user is authenticated.

        Args:
            timeout: Timeout for manual login in seconds

        Returns:
            True if authenticated

        Raises:
            AuthenticationError: If authentication fails
        """
        return await self.auth.ensure_authenticated(timeout=timeout)

    async def dry_run(
        self,
        start_date: date,
        end_date: date,
    ) -> DryRunResult:
        """Perform a dry run to count photos that would be deleted.

        Args:
            start_date: Start date of range
            end_date: End date of range

        Returns:
            DryRunResult with photo counts

        Raises:
            InvalidDateRangeError: If date range is invalid
            AuthenticationError: If not authenticated
        """
        self._validate_date_range(start_date, end_date)

        # Ensure authenticated
        await self.ensure_authenticated()

        # Get photo summary
        summaries = await self.operations.get_photo_summary_by_date(
            start_date, end_date
        )

        total_count = sum(s.count for s in summaries)

        logger.info(
            "Dry run complete: %d photos found in range %s to %s",
            total_count,
            start_date,
            end_date,
        )

        return DryRunResult(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            total_count=total_count,
            photos_by_date=summaries,
        )

    async def delete_photos(
        self,
        start_date: date,
        end_date: date,
        *,
        dry_run: bool = True,
        confirmed: bool = False,
        expected_total: int | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_event: asyncio.Event | None = None,
        state: DeletionState | None = None,
    ) -> DeletionResult:
        """Delete photos in a date range.

        Args:
            start_date: Start date of range
            end_date: End date of range
            dry_run: If True, only count photos without deleting
            confirmed: Must be True to actually delete (safety check)
            expected_total: Pre-computed photo count (from a prior dry run).
                If provided, the initial counting pass is skipped — the
                streaming deleter uses this value only for progress
                reporting and will still walk the entire range to find
                and delete photos. This roughly halves the wall-clock time
                when the caller has already performed a dry run.
            on_progress: Optional callback for progress updates
            cancel_event: Optional ``asyncio.Event``. When set mid-run,
                the streaming deleter exits at the next checkpoint and
                the session is marked ``interrupted`` (resumable).
            state: Optional pre-created ``DeletionState``. Callers that
                need the ``session_id`` before scheduling the work
                (typical for async background tasks) can construct the
                state up front and pass it in. If omitted, a new state
                is created internally.

        Returns:
            DeletionResult with deletion statistics

        Raises:
            InvalidDateRangeError: If date range is invalid
            AuthenticationError: If not authenticated
            ValueError: If attempting to delete without confirmation
        """
        self._validate_date_range(start_date, end_date)

        if not dry_run and not confirmed:
            raise ValueError(
                "Deletion requires explicit confirmation. Set confirmed=True."
            )

        # Ensure authenticated
        await self.ensure_authenticated()

        if dry_run:
            # Just count photos
            result = await self.dry_run(start_date, end_date)
            return DeletionResult(
                mode="dry_run",
                target_count=result.total_count,
                deleted_count=0,
            )

        # Determine total for progress reporting. If the caller already
        # knows the count (from a prior dry run), use it directly and skip
        # the expensive initial counting pass — it would otherwise walk the
        # whole timeline once before the deletion walk, doubling the wall-
        # clock time. We deliberately do NOT pre-collect ids: Google Photos
        # virtualizes its grid, so ids we collect during this initial pass
        # would already be out of the DOM by the time we tried to select
        # them. The streaming deleter below re-walks the timeline and
        # deletes each photo while it is still rendered.
        if expected_total is not None and expected_total >= 0:
            total_count = expected_total
            logger.info(
                "Using caller-provided expected_total=%d; skipping initial count pass",
                expected_total,
            )
        else:
            total_count = await self.operations.count_photos_in_range(
                start_date, end_date
            )

        if total_count == 0:
            if state is not None:
                # Caller-provided state: record completion so polling can
                # observe "done" even for empty ranges.
                state.total_count = 0
                state.mark_completed()
                await self.state_service.save(state)
            return DeletionResult(
                mode="delete",
                target_count=0,
                deleted_count=0,
            )

        # Create state for tracking (unless caller already supplied one)
        if state is None:
            state = DeletionState(
                start_date=start_date,
                end_date=end_date,
                total_count=total_count,
            )
        else:
            state.total_count = total_count
        state.mark_in_progress()
        await self.state_service.save(state)

        return await self._run_streaming_delete(
            state=state,
            start_date=start_date,
            end_date=end_date,
            total_count=total_count,
            mode="delete",
            on_progress=on_progress,
            cancel_event=cancel_event,
        )

    async def resume_deletion(
        self,
        session_id: str,
        on_progress: ProgressCallback | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> DeletionResult:
        """Resume an interrupted deletion session.

        Args:
            session_id: Session ID to resume
            on_progress: Optional callback for progress updates
            cancel_event: Optional cancel signal (see ``delete_photos``).

        Returns:
            DeletionResult with deletion statistics

        Raises:
            ValueError: If session not found or not resumable
        """
        state = await self.state_service.load(session_id)

        if state is None:
            raise ValueError(f"Session not found: {session_id}")

        if not state.is_resumable:
            raise ValueError(f"Session is not resumable (status: {state.status})")

        # Ensure authenticated (resume bypasses delete_photos, so we must
        # check here explicitly).
        await self.ensure_authenticated()

        # Resume strategy: just re-run the streaming deletion over the
        # same range. Photos that were already deleted in the previous run
        # have been moved to trash and no longer appear in the main
        # timeline, so the streaming deleter naturally skips them. There
        # is no need to match ``last_processed_id`` — that was only needed
        # for the old pre-collect + iterate flow, which could re-see
        # already-processed photos in its pre-collected list.

        state.mark_in_progress()
        await self.state_service.save(state)

        return await self._run_streaming_delete(
            state=state,
            start_date=state.start_date,
            end_date=state.end_date,
            total_count=state.total_count,
            mode="resume",
            on_progress=on_progress,
            cancel_event=cancel_event,
        )

    async def _run_streaming_delete(
        self,
        *,
        state: DeletionState,
        start_date: date,
        end_date: date,
        total_count: int,
        mode: str,
        on_progress: ProgressCallback | None,
        cancel_event: asyncio.Event | None,
    ) -> DeletionResult:
        """Shared core for ``delete_photos`` and ``resume_deletion``.

        Runs the streaming deleter with progress + cancel hooks, then
        marks the session as completed / interrupted / failed as
        appropriate and persists the final result counts onto ``state``.
        """
        progress_save_every = 5

        async def _on_photo_deleted(photo_id: str) -> None:
            state.increment_processed(photo_id)
            if state.processed_count % progress_save_every == 0:
                await self.state_service.save(state)
            # Also treat on_photo_deleted as a cancel checkpoint — it is
            # the tightest-grain callback we have, so checking here makes
            # stop latency at most one photo while the streaming deleter
            # is actively progressing.
            if cancel_event is not None and cancel_event.is_set():
                raise DeletionCancelledError(
                    f"Deletion cancelled after {state.processed_count} photo(s)"
                )

        async def _on_progress(processed: int, total: int, photo_id: str) -> None:
            if on_progress is not None:
                await on_progress(processed, total, photo_id)

        try:
            (
                deleted_count,
                failed_ids,
            ) = await self.operations.delete_photos_in_range_streaming(
                start_date,
                end_date,
                expected_total=total_count,
                on_progress=_on_progress,
                on_photo_deleted=_on_photo_deleted,
                cancel_event=cancel_event,
            )

            state.set_result_counts(deleted_count, failed_ids)
            state.mark_completed()
            await self.state_service.save(state)

        except DeletionCancelledError:
            # Preserve whatever counts we accumulated so far and record
            # any failures the streaming deleter returned before the
            # cancellation. ``deleted_count`` on the state was kept in
            # sync via ``increment_processed``; ``failed_photo_ids`` may
            # already hold partial entries from earlier failures, so we
            # do NOT overwrite them here.
            state.mark_interrupted()
            await self.state_service.save(state)
            return DeletionResult(
                mode=mode,
                target_count=total_count,
                deleted_count=state.deleted_count,
                failed_count=state.failed_count,
                failed_photo_ids=list(state.failed_photo_ids),
            )
        except Exception:
            # Unknown error: mark interrupted so the user can try to
            # resume, but re-raise so the caller can surface the failure.
            state.mark_interrupted()
            await self.state_service.save(state)
            raise

        return DeletionResult(
            mode=mode,
            target_count=total_count,
            deleted_count=deleted_count,
            failed_count=len(failed_ids),
            failed_photo_ids=failed_ids,
        )

    async def get_interrupted_session(self) -> DeletionState | None:
        """Get any interrupted deletion session.

        Returns:
            DeletionState if found, None otherwise
        """
        return await self.state_service.find_interrupted()

    async def cancel_session(self, session_id: str) -> bool:
        """Cancel and delete a session.

        Args:
            session_id: Session ID to cancel

        Returns:
            True if session was deleted
        """
        return await self.state_service.delete(session_id)
