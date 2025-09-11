# core/retry_handler.py
import asyncio
import random
import time
from typing import Any, Callable, Dict, Optional, Union
import logging
from core.config import config

log = logging.getLogger("tausendsassa.retry")

class ExponentialBackoff:
    """Exponential backoff calculator with jitter"""
    
    def __init__(self, base_delay: float = 2.0, max_delay: float = 300.0, jitter: bool = True):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
    
    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number (0-based)"""
        delay = min(self.base_delay * (2 ** attempt), self.max_delay)
        
        if self.jitter:
            # Add ±25% jitter to prevent thundering herd
            jitter_range = delay * 0.25
            delay += random.uniform(-jitter_range, jitter_range)
        
        return max(0, delay)

class RetryContext:
    """Context for tracking retry attempts"""
    
    def __init__(self, operation_id: str):
        self.operation_id = operation_id
        self.attempts = 0
        self.last_attempt = 0.0
        self.last_error: Optional[Exception] = None
        self.consecutive_failures = 0
        self.last_success = 0.0

class RetryHandler:
    """Handles retry logic with exponential backoff and failure tracking"""
    
    def __init__(self):
        self.backoff = ExponentialBackoff(
            base_delay=config.base_retry_delay,
            max_delay=300.0,  # 5 minutes max
            jitter=True
        )
        self.contexts: Dict[str, RetryContext] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
    
    def start_cleanup_task(self):
        """Start periodic cleanup of old contexts"""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
    
    def stop_cleanup_task(self):
        """Stop cleanup task"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
    
    async def _periodic_cleanup(self):
        """Clean up old retry contexts"""
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour
                current_time = time.time()
                
                # Remove contexts older than 24 hours
                old_contexts = [
                    op_id for op_id, ctx in self.contexts.items()
                    if current_time - ctx.last_attempt > 86400
                ]
                
                for op_id in old_contexts:
                    del self.contexts[op_id]
                
                if old_contexts:
                    log.debug(f"Cleaned up {len(old_contexts)} old retry contexts")
                    
            except Exception as e:
                log.error(f"Error in retry context cleanup: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes on error
    
    def get_context(self, operation_id: str) -> RetryContext:
        """Get or create retry context for operation"""
        if operation_id not in self.contexts:
            self.contexts[operation_id] = RetryContext(operation_id)
        return self.contexts[operation_id]
    
    def should_retry(self, operation_id: str, exception: Exception) -> bool:
        """Determine if operation should be retried"""
        context = self.get_context(operation_id)
        
        # Check max attempts
        if context.attempts >= config.max_retries:
            log.warning(f"Max retries ({config.max_retries}) exceeded for {operation_id}")
            return False
        
        # Check if this is a retryable exception
        if not self._is_retryable_exception(exception):
            log.debug(f"Non-retryable exception for {operation_id}: {type(exception).__name__}")
            return False
        
        return True
    
    def _is_retryable_exception(self, exception: Exception) -> bool:
        """Determine if exception is retryable"""
        # Network-related exceptions are retryable
        retryable_exceptions = (
            asyncio.TimeoutError,
            ConnectionError,
            OSError,  # Includes network errors
        )
        
        # Check if it's a known retryable exception
        if isinstance(exception, retryable_exceptions):
            return True
        
        # Check for aiohttp exceptions
        try:
            import aiohttp
            if isinstance(exception, (
                aiohttp.ClientError,
                aiohttp.ServerTimeoutError,
                aiohttp.ClientConnectorError,
                aiohttp.ClientResponseError
            )):
                # Don't retry 4xx client errors (except 429 rate limit)
                if hasattr(exception, 'status') and 400 <= exception.status < 500:
                    return exception.status == 429  # Retry rate limits
                return True
        except ImportError:
            pass
        
        # Check for common HTTP library exceptions
        try:
            import requests
            if isinstance(exception, (
                requests.ConnectionError,
                requests.Timeout,
                requests.HTTPError
            )):
                # Same logic for requests
                if hasattr(exception, 'response') and exception.response is not None:
                    status = exception.response.status_code
                    if 400 <= status < 500:
                        return status == 429
                return True
        except ImportError:
            pass
        
        return False
    
    async def execute_with_retry(
        self,
        operation_id: str,
        operation: Callable,
        *args,
        **kwargs
    ) -> Any:
        """Execute operation with retry logic"""
        context = self.get_context(operation_id)
        
        while True:
            try:
                context.attempts += 1
                context.last_attempt = time.time()
                
                # Execute the operation
                result = await operation(*args, **kwargs)
                
                # Success - reset failure tracking
                context.consecutive_failures = 0
                context.last_success = time.time()
                context.last_error = None
                
                log.debug(f"Operation {operation_id} succeeded on attempt {context.attempts}")
                return result
                
            except Exception as e:
                context.last_error = e
                context.consecutive_failures += 1
                
                if not self.should_retry(operation_id, e):
                    log.error(f"Operation {operation_id} failed permanently: {e}")
                    raise e
                
                # Calculate delay for next attempt
                delay = self.backoff.calculate_delay(context.attempts - 1)
                
                log.warning(
                    f"Operation {operation_id} failed (attempt {context.attempts}), "
                    f"retrying in {delay:.1f}s: {e}"
                )
                
                await asyncio.sleep(delay)
    
    def record_failure(self, operation_id: str, exception: Exception):
        """Record a failure without retry (for tracking purposes)"""
        context = self.get_context(operation_id)
        context.consecutive_failures += 1
        context.last_error = exception
        context.last_attempt = time.time()
    
    def record_success(self, operation_id: str):
        """Record a success (for tracking purposes)"""
        context = self.get_context(operation_id)
        context.consecutive_failures = 0
        context.last_success = time.time()
        context.last_error = None
    
    def get_failure_count(self, operation_id: str) -> int:
        """Get consecutive failure count for operation"""
        if operation_id in self.contexts:
            return self.contexts[operation_id].consecutive_failures
        return 0
    
    def is_operation_healthy(self, operation_id: str, threshold: int = None) -> bool:
        """Check if operation is healthy (below failure threshold)"""
        if threshold is None:
            threshold = config.failure_threshold
        
        return self.get_failure_count(operation_id) < threshold

# Global retry handler instance
retry_handler = RetryHandler()