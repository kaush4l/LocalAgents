"""
Error classification for intelligent retry and failover decisions.
"""
from typing import Literal, Optional

FailoverReason = Literal["rate_limit", "billing", "auth", "timeout", "format", "unknown"]


def classify_error(error: Exception) -> Optional[FailoverReason]:
    """Classify an error to determine retry/failover strategy.
    
    Returns:
        FailoverReason if classified, None if error should not trigger failover
    """
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()
    
    # Rate limit patterns
    if any(p in error_str for p in ["rate_limit", "rate limit", "429", "too many requests", "quota"]):
        return "rate_limit"
    
    # Billing/payment patterns
    if any(p in error_str for p in ["billing", "payment", "insufficient", "credit", "balance"]):
        return "billing"
    
    # Auth patterns
    if any(p in error_str for p in ["auth", "401", "403", "unauthorized", "forbidden", "api key", "invalid key"]):
        return "auth"
    
    # Timeout patterns
    if any(p in error_str or p in error_type for p in ["timeout", "timed out", "deadline"]):
        return "timeout"
    
    # Format/parsing patterns
    if any(p in error_str or p in error_type for p in ["json", "parse", "format", "validation", "pydantic"]):
        return "format"
    
    return None


def should_failover(reason: Optional[FailoverReason]) -> bool:
    """Determine if we should try a different model based on error reason."""
    # Rate limit and billing should trigger failover to backup model
    # Auth errors on specific model should failover
    # Format errors are usually prompt issues, not model issues
    return reason in ("rate_limit", "billing", "auth")


def should_retry(reason: Optional[FailoverReason]) -> bool:
    """Determine if we should retry the same model."""
    # Timeout and format errors can be retried
    # Rate limit might work after backoff
    return reason in ("timeout", "format", "rate_limit")
