"""
Production utilities package for real estate AI calling agent.

Modules:
- supabase_client: Safe Supabase REST API client with URL encoding
- resilience: Retry logic and circuit breaker pattern
- validation: Input validation and sanitization
"""

from .supabase_client import SupabaseClient
from .resilience import retry_with_backoff, CircuitBreaker, CircuitBreakerState
from .validation import (
    validate_phone_number,
    validate_scenario,
    sanitize_transcript,
    validate_post_call_payload,
    ValidationError,
)

__all__ = [
    "SupabaseClient",
    "retry_with_backoff",
    "CircuitBreaker",
    "CircuitBreakerState",
    "validate_phone_number",
    "validate_scenario",
    "sanitize_transcript",
    "validate_post_call_payload",
    "ValidationError",
]
