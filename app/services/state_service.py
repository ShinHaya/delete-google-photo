"""State management service for tracking deletion progress."""

import json
import logging
from pathlib import Path

from app.config import settings
from app.exceptions import StateError
from app.models.state import DeletionState, DeletionStatus

logger = logging.getLogger(__name__)


class StateService:
    """Manages persistence of deletion state for resume functionality."""

    def __init__(self, state_dir: Path | None = None) -> None:
        """Initialize state service.

        Args:
            state_dir: Directory for state files (default from settings)
        """
        self.state_dir = state_dir or settings.state_dir
        self._ensure_state_dir()

    def _ensure_state_dir(self) -> None:
        """Ensure state directory exists."""
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _get_state_file(self, session_id: str) -> Path:
        """Get path to state file for a session.

        Args:
            session_id: Session identifier

        Returns:
            Path to state file
        """
        return self.state_dir / f"{session_id}.json"

    async def save(self, state: DeletionState) -> None:
        """Save deletion state to file.

        Args:
            state: State to save

        Raises:
            StateError: If save fails
        """
        try:
            state_file = self._get_state_file(state.session_id)
            state_dict = state.model_dump(mode="json")

            with state_file.open("w", encoding="utf-8") as f:
                json.dump(state_dict, f, indent=2, default=str)

            # Set restrictive permissions (owner read/write only)
            state_file.chmod(0o600)

            logger.info("State saved for session %s", state.session_id)

        except Exception as e:
            raise StateError(f"Failed to save state: {e}") from e

    async def load(self, session_id: str) -> DeletionState | None:
        """Load deletion state from file.

        Args:
            session_id: Session identifier

        Returns:
            DeletionState if found, None otherwise

        Raises:
            StateError: If load fails (file exists but cannot be parsed)
        """
        state_file = self._get_state_file(session_id)

        if not state_file.exists():
            return None

        try:
            with state_file.open("r", encoding="utf-8") as f:
                state_dict = json.load(f)

            return DeletionState(**state_dict)

        except json.JSONDecodeError as e:
            raise StateError(f"Invalid state file format: {e}") from e
        except Exception as e:
            raise StateError(f"Failed to load state: {e}") from e

    async def delete(self, session_id: str) -> bool:
        """Delete state file for a session.

        Args:
            session_id: Session identifier

        Returns:
            True if deleted, False if file didn't exist
        """
        state_file = self._get_state_file(session_id)

        if not state_file.exists():
            return False

        try:
            state_file.unlink()
            logger.info("State deleted for session %s", session_id)
            return True
        except Exception as e:
            logger.error("Failed to delete state file: %s", e)
            return False

    async def list_sessions(self) -> list[str]:
        """List all session IDs with saved state.

        Returns:
            List of session IDs
        """
        sessions = []
        for state_file in self.state_dir.glob("*.json"):
            sessions.append(state_file.stem)
        return sessions

    async def find_interrupted(self) -> DeletionState | None:
        """Find any interrupted deletion session.

        Returns:
            DeletionState if an interrupted session exists, None otherwise
        """
        for session_id in await self.list_sessions():
            state = await self.load(session_id)
            if state and state.status == DeletionStatus.INTERRUPTED:
                logger.info("Found interrupted session: %s", session_id)
                return state
        return None

    async def find_in_progress(self) -> DeletionState | None:
        """Find any in-progress deletion session.

        Returns:
            DeletionState if an in-progress session exists, None otherwise
        """
        for session_id in await self.list_sessions():
            state = await self.load(session_id)
            if state and state.status == DeletionStatus.IN_PROGRESS:
                logger.info("Found in-progress session: %s", session_id)
                return state
        return None

    async def cleanup_completed(self) -> int:
        """Delete state files for completed sessions.

        Returns:
            Number of state files deleted
        """
        deleted_count = 0
        for session_id in await self.list_sessions():
            state = await self.load(session_id)
            if (
                state
                and state.status == DeletionStatus.COMPLETED
                and await self.delete(session_id)
            ):
                deleted_count += 1

        if deleted_count > 0:
            logger.info("Cleaned up %d completed session(s)", deleted_count)

        return deleted_count

    async def update_progress(
        self,
        session_id: str,
        processed_count: int,
        last_processed_id: str | None = None,
    ) -> DeletionState | None:
        """Update progress for a session.

        Args:
            session_id: Session identifier
            processed_count: New processed count
            last_processed_id: ID of last processed photo

        Returns:
            Updated state, or None if session not found
        """
        state = await self.load(session_id)
        if state is None:
            return None

        state.processed_count = processed_count
        if last_processed_id:
            state.last_processed_id = last_processed_id

        await self.save(state)
        return state
