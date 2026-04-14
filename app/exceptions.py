"""Custom exceptions for the application."""


class GooglePhotoDeleteError(Exception):
    """Base exception for this application."""

    def __init__(self, message: str = "An error occurred") -> None:
        self.message = message
        super().__init__(self.message)


class AuthenticationError(GooglePhotoDeleteError):
    """Authentication failed."""

    def __init__(self, message: str = "Authentication failed") -> None:
        super().__init__(message)


class SessionExpiredError(AuthenticationError):
    """Session has expired."""

    def __init__(self, message: str = "Session has expired") -> None:
        super().__init__(message)


class PhotoNotFoundError(GooglePhotoDeleteError):
    """Photo not found."""

    def __init__(self, photo_id: str | None = None) -> None:
        message = f"Photo not found: {photo_id}" if photo_id else "Photo not found"
        super().__init__(message)
        self.photo_id = photo_id


class PhotoDeletionError(GooglePhotoDeleteError):
    """Failed to delete photo."""

    def __init__(
        self, photo_id: str | None = None, message: str = "Failed to delete photo"
    ) -> None:
        if photo_id:
            message = f"{message}: {photo_id}"
        super().__init__(message)
        self.photo_id = photo_id


class RateLimitError(GooglePhotoDeleteError):
    """Rate limit exceeded."""

    def __init__(
        self, retry_after: int | None = None, message: str = "Rate limit exceeded"
    ) -> None:
        if retry_after:
            message = f"{message}. Retry after {retry_after} seconds"
        super().__init__(message)
        self.retry_after = retry_after


class BrowserError(GooglePhotoDeleteError):
    """Browser operation failed."""

    def __init__(self, message: str = "Browser operation failed") -> None:
        super().__init__(message)


class StateError(GooglePhotoDeleteError):
    """State management error."""

    def __init__(self, message: str = "State management error") -> None:
        super().__init__(message)


class InvalidDateRangeError(GooglePhotoDeleteError):
    """Invalid date range specified."""

    def __init__(self, message: str = "Invalid date range") -> None:
        super().__init__(message)
