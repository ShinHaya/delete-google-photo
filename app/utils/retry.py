"""Retry utilities with exponential backoff."""

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.config import settings
from app.exceptions import GooglePhotoDeleteError, RateLimitError

logger = logging.getLogger(__name__)

T = TypeVar("T")


def exponential_backoff(
    retry_count: int,
    initial_delay: float = 1.0,
    max_wait: float = 10.0,
) -> float:
    """Calculate exponential backoff delay.

    Formula: min(max_wait, initial_delay * 2^(retry_count - 1))

    Args:
        retry_count: Current retry attempt (1-indexed)
        initial_delay: Initial delay in seconds (default: 1.0)
        max_wait: Maximum delay in seconds (default: 10.0)

    Returns:
        Delay in seconds
    """
    if retry_count < 1:
        return initial_delay
    delay = initial_delay * (2 ** (retry_count - 1))
    return float(min(max_wait, delay))


async def retry_with_backoff(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    max_retries: int | None = None,
    initial_delay: float | None = None,
    max_delay: float | None = None,
    retryable_exceptions: tuple[type[Exception], ...] = (GooglePhotoDeleteError,),
    **kwargs: Any,
) -> T:
    """Execute an async function with retry and exponential backoff.

    Args:
        func: Async function to execute
        *args: Positional arguments for the function
        max_retries: Maximum number of retry attempts (default from settings)
        initial_delay: Initial delay in seconds (default from settings)
        max_delay: Maximum delay in seconds (default from settings)
        retryable_exceptions: Tuple of exceptions to retry on
        **kwargs: Keyword arguments for the function

    Returns:
        Result of the function

    Raises:
        Exception: The last exception if all retries fail
    """
    max_retries = max_retries if max_retries is not None else settings.max_retry_count
    initial_delay = (
        initial_delay if initial_delay is not None else settings.initial_retry_delay
    )
    max_delay = max_delay if max_delay is not None else settings.max_retry_delay

    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except retryable_exceptions as e:
            last_exception = e

            if attempt == max_retries:
                logger.error(
                    "All %d retry attempts failed for %s: %s",
                    max_retries,
                    func.__name__,
                    e,
                )
                raise

            # Handle rate limit with specific retry-after
            delay: float
            if isinstance(e, RateLimitError) and e.retry_after:
                delay = float(e.retry_after)
            else:
                delay = exponential_backoff(
                    attempt + 1,
                    initial_delay=initial_delay,
                    max_wait=max_delay,
                )

            logger.warning(
                "Attempt %d/%d failed for %s: %s. Retrying in %.1f seconds...",
                attempt + 1,
                max_retries + 1,
                func.__name__,
                e,
                delay,
            )

            await asyncio.sleep(delay)

    # This should never be reached, but just in case
    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected state in retry loop")


def with_retry(
    max_retries: int | None = None,
    initial_delay: float | None = None,
    max_delay: float | None = None,
    retryable_exceptions: tuple[type[Exception], ...] = (GooglePhotoDeleteError,),
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator to add retry with exponential backoff to an async function.

    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        retryable_exceptions: Tuple of exceptions to retry on

    Returns:
        Decorated function with retry logic
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await retry_with_backoff(
                func,
                *args,
                max_retries=max_retries,
                initial_delay=initial_delay,
                max_delay=max_delay,
                retryable_exceptions=retryable_exceptions,
                **kwargs,
            )

        return wrapper

    return decorator
