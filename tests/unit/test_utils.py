"""Unit tests for utility functions."""

import pytest

from app.exceptions import GooglePhotoDeleteError, RateLimitError
from app.utils.retry import exponential_backoff, retry_with_backoff, with_retry


class TestExponentialBackoff:
    """Tests for exponential_backoff function."""

    @pytest.mark.parametrize(
        "retry_count,expected",
        [
            (1, 1.0),  # 1 * 2^0 = 1
            (2, 2.0),  # 1 * 2^1 = 2
            (3, 4.0),  # 1 * 2^2 = 4
            (4, 8.0),  # 1 * 2^3 = 8
            (5, 10.0),  # min(10, 16) = 10 (capped at max_wait)
            (6, 10.0),  # min(10, 32) = 10 (capped at max_wait)
        ],
    )
    def test_backoff_calculation(self, retry_count: int, expected: float) -> None:
        """Test backoff calculation with default parameters."""
        result = exponential_backoff(retry_count, initial_delay=1.0, max_wait=10.0)
        assert result == expected

    def test_custom_initial_delay(self) -> None:
        """Test backoff with custom initial delay."""
        result = exponential_backoff(1, initial_delay=2.0, max_wait=10.0)
        assert result == 2.0  # 2 * 2^0 = 2

        result = exponential_backoff(2, initial_delay=2.0, max_wait=10.0)
        assert result == 4.0  # 2 * 2^1 = 4

    def test_custom_max_wait(self) -> None:
        """Test backoff with custom max wait."""
        result = exponential_backoff(5, initial_delay=1.0, max_wait=5.0)
        assert result == 5.0  # min(5, 16) = 5

    def test_zero_retry_count(self) -> None:
        """Test backoff with zero retry count returns initial delay."""
        result = exponential_backoff(0, initial_delay=1.0, max_wait=10.0)
        assert result == 1.0

    def test_negative_retry_count(self) -> None:
        """Test backoff with negative retry count returns initial delay."""
        result = exponential_backoff(-1, initial_delay=1.0, max_wait=10.0)
        assert result == 1.0


class TestRetryWithBackoff:
    """Tests for retry_with_backoff function."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self) -> None:
        """Test function that succeeds on first attempt."""
        call_count = 0

        async def success_func() -> str:
            nonlocal call_count
            call_count += 1
            return "success"

        result = await retry_with_backoff(
            success_func,
            max_retries=3,
            initial_delay=0.01,
            max_delay=0.1,
        )
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_success_after_retry(self) -> None:
        """Test function that succeeds after a few retries."""
        call_count = 0

        async def flaky_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise GooglePhotoDeleteError("Temporary error")
            return "success"

        result = await retry_with_backoff(
            flaky_func,
            max_retries=3,
            initial_delay=0.01,
            max_delay=0.1,
        )
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_all_retries_fail(self) -> None:
        """Test function that fails all retries."""
        call_count = 0

        async def always_fail() -> str:
            nonlocal call_count
            call_count += 1
            raise GooglePhotoDeleteError("Permanent error")

        with pytest.raises(GooglePhotoDeleteError, match="Permanent error"):
            await retry_with_backoff(
                always_fail,
                max_retries=3,
                initial_delay=0.01,
                max_delay=0.1,
            )
        assert call_count == 4  # Initial attempt + 3 retries

    @pytest.mark.asyncio
    async def test_non_retryable_exception(self) -> None:
        """Test that non-retryable exceptions are not retried."""
        call_count = 0

        async def raise_value_error() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("Not retryable")

        with pytest.raises(ValueError, match="Not retryable"):
            await retry_with_backoff(
                raise_value_error,
                max_retries=3,
                initial_delay=0.01,
                max_delay=0.1,
                retryable_exceptions=(GooglePhotoDeleteError,),
            )
        assert call_count == 1  # Only one attempt, no retries

    @pytest.mark.asyncio
    async def test_rate_limit_with_retry_after(self) -> None:
        """Test that RateLimitError with retry_after uses that delay."""
        call_count = 0

        async def rate_limited() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RateLimitError(retry_after=1)
            return "success"

        result = await retry_with_backoff(
            rate_limited,
            max_retries=3,
            initial_delay=0.01,
            max_delay=0.1,
        )
        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_with_args_and_kwargs(self) -> None:
        """Test retry with function arguments."""
        call_count = 0

        async def func_with_args(a: int, b: str, c: bool = False) -> dict[str, object]:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise GooglePhotoDeleteError("Retry")
            return {"a": a, "b": b, "c": c}

        result = await retry_with_backoff(
            func_with_args,
            42,
            "test",
            c=True,
            max_retries=3,
            initial_delay=0.01,
            max_delay=0.1,
        )
        assert result == {"a": 42, "b": "test", "c": True}
        assert call_count == 2


class TestWithRetryDecorator:
    """Tests for with_retry decorator."""

    @pytest.mark.asyncio
    async def test_decorator_success(self) -> None:
        """Test decorator with successful function."""
        call_count = 0

        @with_retry(max_retries=3, initial_delay=0.01, max_delay=0.1)
        async def decorated_func() -> str:
            nonlocal call_count
            call_count += 1
            return "decorated success"

        result = await decorated_func()
        assert result == "decorated success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_decorator_with_retry(self) -> None:
        """Test decorator with function that needs retry."""
        call_count = 0

        @with_retry(max_retries=3, initial_delay=0.01, max_delay=0.1)
        async def flaky_decorated() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise GooglePhotoDeleteError("Flaky")
            return "eventually success"

        result = await flaky_decorated()
        assert result == "eventually success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_decorator_preserves_function_name(self) -> None:
        """Test that decorator preserves function metadata."""

        @with_retry(max_retries=3, initial_delay=0.01, max_delay=0.1)
        async def named_function() -> str:
            """A docstring."""
            return "result"

        assert named_function.__name__ == "named_function"
        assert named_function.__doc__ == "A docstring."
