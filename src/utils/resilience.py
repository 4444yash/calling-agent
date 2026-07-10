"""
Resilience patterns: retries, circuit breaker, timeout handling.
Production-ready reliability utilities.
"""
import asyncio
import time
from enum import Enum
from typing import Callable, Any, TypeVar, Optional
from loguru import logger
import httpx

T = TypeVar('T')


class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"          # Normal operation
    OPEN = "open"              # Failing, reject requests
    HALF_OPEN = "half_open"    # Testing recovery


class CircuitBreaker:
    """
    Circuit breaker pattern for protecting against cascading failures.
    
    Usage:
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=30)
        result = await cb.call(async_function)
    """
    
    def __init__(self, name: str = "circuit_breaker", 
                 failure_threshold: int = 5, 
                 timeout_seconds: int = 60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.state = CircuitBreakerState.CLOSED
    
    async def call(self, async_fn: Callable[[], Any], 
                  fallback: Optional[Any] = None) -> Any:
        """
        Execute async function with circuit breaker protection.
        
        If circuit is OPEN, returns fallback value instead of executing.
        If HALF_OPEN, tries execution and either closes (success) or opens (failure).
        """
        if self.state == CircuitBreakerState.OPEN:
            elapsed = time.time() - self.last_failure_time
            if elapsed > self.timeout_seconds:
                self.state = CircuitBreakerState.HALF_OPEN
                logger.info(f"🔌 [{self.name}] HALF_OPEN: testing recovery...")
            else:
                if fallback is not None:
                    logger.warning(f"🔌 [{self.name}] OPEN: returning fallback")
                    return fallback
                raise Exception(f"Circuit breaker {self.name} is OPEN")
        
        try:
            result = await async_fn()
            
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.state = CircuitBreakerState.CLOSED
                self.failure_count = 0
                logger.info(f"🔌 [{self.name}] CLOSED: recovery successful ✓")
            
            return result
            
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitBreakerState.OPEN
                logger.error(f"🔌 [{self.name}] OPEN: after {self.failure_count} failures")
            
            raise


async def retry_with_backoff(
    async_fn: Callable[[], T],
    max_retries: int = 3,
    backoff_factor: float = 1.5,
    initial_delay: float = 1.0,
    max_delay: float = 3.0,  # ✅ CHANGED FROM 10.0 TO 3.0 - Cap delay for voice calls
    max_total_time: float = 3.0,  # ✅ ADD THIS PARAMETER - Never retry longer than this
    name: str = "operation"
) -> T:
    """
    Retry async function with exponential backoff.
    
    Delays: 1.0s, 1.5s, 2.25s (with backoff_factor=1.5)
    Max total retry time capped at max_total_time to prevent 7-10s hangs in voice calls.
    
    Usage:
        result = await retry_with_backoff(
            lambda: supabase_client.get_customers_by_phone("+919876543210"),
            max_retries=3,
            backoff_factor=1.5,
            max_total_time=3.0
        )
    """
    last_exception = None
    current_delay = initial_delay
    start_time = time.time()
    
    for attempt in range(max_retries):
        try:
            return await async_fn()
            
        except asyncio.TimeoutError as e:
            last_exception = e
            logger.warning(f"⏱️  [{name}] Attempt {attempt + 1}/{max_retries} timed out")
            
        except httpx.HTTPError as e:
            last_exception = e
            logger.warning(f"📡 [{name}] Attempt {attempt + 1}/{max_retries} HTTP error: {e}")
            
        except Exception as e:
            last_exception = e
            logger.warning(f"❌ [{name}] Attempt {attempt + 1}/{max_retries} failed: {e}")
        
        if attempt < max_retries - 1:
            elapsed = time.time() - start_time
            remaining = max_total_time - elapsed
            
            # ✅ CAP THE DELAY - Don't wait longer than remaining time
            wait_time = min(current_delay, remaining)
            if wait_time > 0:
                logger.info(f"⏳ [{name}] Retrying in {wait_time:.1f}s (total: {elapsed:.1f}s/{max_total_time}s)...")
                await asyncio.sleep(wait_time)
                
                # ✅ CHECK TIME LIMIT BEFORE EXPONENTIAL INCREASE
                if time.time() - start_time > max_total_time:
                    logger.warning(f"❌ [{name}] Exceeded max retry time ({max_total_time}s) — giving up")
                    break
                
                current_delay = min(current_delay * backoff_factor, max_delay)  # ✅ CAP AT max_delay
            else:
                logger.warning(f"❌ [{name}] Exceeded max retry time ({max_total_time}s)")
                break
        else:
            logger.error(f"❌ [{name}] All {max_retries} retries exhausted")
    
    if last_exception:
        raise last_exception
    
    raise Exception(f"{name} failed after {max_retries} retries")


async def call_with_timeout(
    async_fn: Callable[[], T],
    timeout_seconds: float,
    name: str = "operation"
) -> T:
    """
    Execute async function with explicit timeout.
    
    Raises: asyncio.TimeoutError if exceeds timeout_seconds
    """
    try:
        return await asyncio.wait_for(async_fn(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.error(f"⏱️  [{name}] Timed out after {timeout_seconds}s")
        raise


async def execute_with_fallback(
    primary_fn: Callable[[], T],
    fallback_fn: Callable[[], T],
    timeout_seconds: float = 2.0,
    name: str = "operation"
) -> T:
    """
    Try primary function, fall back to secondary if it fails or times out.
    
    Usage:
        metadata = await execute_with_fallback(
            primary_fn=lambda: supabase_client.get_customers_by_phone(phone),
            fallback_fn=lambda: {},
            timeout_seconds=2.0
        )
    """
    try:
        return await call_with_timeout(primary_fn, timeout_seconds, name)
    except (asyncio.TimeoutError, httpx.HTTPError, Exception) as e:
        logger.warning(f"⚠️  [{name}] Primary failed, using fallback: {e}")
        try:
            return await fallback_fn()
        except Exception as fallback_error:
            logger.error(f"❌ [{name}] Fallback also failed: {fallback_error}")
            raise
