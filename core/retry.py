"""
Retry utilities with exponential backoff for transient failures.
Simple, focused implementation for personal project use.
"""
import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Callable, TypeVar, Optional

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    attempts: int = 3
    min_delay_ms: int = 300
    max_delay_ms: int = 30000
    jitter: float = 0.1  # Random factor 0-1 to add to delay
    
    def delay_for_attempt(self, attempt: int) -> float:
        """Calculate delay in seconds with exponential backoff + jitter."""
        base_ms = self.min_delay_ms * (2 ** attempt)
        capped_ms = min(base_ms, self.max_delay_ms)
        jitter_ms = capped_ms * self.jitter * random.random()
        return (capped_ms + jitter_ms) / 1000.0


# Default configs for common use cases
INFERENCE_RETRY = RetryConfig(attempts=3, min_delay_ms=500, max_delay_ms=30000)
TOOL_RETRY = RetryConfig(attempts=2, min_delay_ms=300, max_delay_ms=5000)


def is_retryable(error: Exception) -> bool:
    """Check if an error is worth retrying (transient failures)."""
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()
    
    # Rate limits, timeouts, and connection issues are retryable
    retryable_patterns = [
        "rate_limit", "rate limit", "ratelimit",
        "timeout", "timed out",
        "connection", "connect",
        "temporary", "transient",
        "503", "502", "429", "500",
        "overloaded", "capacity",
        "try again"
    ]
    
    for pattern in retryable_patterns:
        if pattern in error_str or pattern in error_type:
            return True
    
    return False


async def retry_async(
    fn: Callable[[], T],
    config: RetryConfig = None,
    should_retry: Callable[[Exception], bool] = None,
    on_retry: Callable[[int, Exception], None] = None
) -> T:
    """Execute an async function with retry on failure.
    
    Args:
        fn: Async function to call (no args, use lambda to wrap)
        config: Retry configuration
        should_retry: Optional custom function to check if error is retryable
        on_retry: Optional callback on each retry (attempt, error)
    
    Returns:
        Result of successful fn() call
    
    Raises:
        Last exception if all attempts fail
    """
    config = config or INFERENCE_RETRY
    should_retry = should_retry or is_retryable
    last_error = None
    
    for attempt in range(config.attempts):
        try:
            if asyncio.iscoroutinefunction(fn):
                return await fn()
            else:
                return fn()
        except Exception as e:
            last_error = e
            
            # Last attempt or non-retryable error
            if attempt >= config.attempts - 1 or not should_retry(e):
                raise
            
            delay = config.delay_for_attempt(attempt)
            logger.warning(f"Retry {attempt + 1}/{config.attempts} after {delay:.2f}s: {type(e).__name__}")
            
            if on_retry:
                on_retry(attempt, e)
            
            await asyncio.sleep(delay)
    
    raise last_error


def retry_sync(
    fn: Callable[[], T],
    config: RetryConfig = None,
    should_retry: Callable[[Exception], bool] = None
) -> T:
    """Synchronous version of retry_async."""
    import time
    
    config = config or TOOL_RETRY
    should_retry = should_retry or is_retryable
    last_error = None
    
    for attempt in range(config.attempts):
        try:
            return fn()
        except Exception as e:
            last_error = e
            
            if attempt >= config.attempts - 1 or not should_retry(e):
                raise
            
            delay = config.delay_for_attempt(attempt)
            logger.warning(f"Retry {attempt + 1}/{config.attempts} after {delay:.2f}s: {type(e).__name__}")
            time.sleep(delay)
    
    raise last_error
