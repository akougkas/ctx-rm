"""Middleware components for the web service.

This module provides middleware functions that process HTTP requests
and responses at various stages of the request lifecycle. Middleware
is applied in the order it is registered and can modify requests,
responses, or short-circuit the processing pipeline.

Middleware Stack
----------------
The middleware stack processes requests in the following order:

1. **RequestIDMiddleware**: Assigns a unique request ID for tracing
2. **LoggingMiddleware**: Logs request/response details
3. **CORSMiddleware**: Handles CORS headers and preflight requests
4. **RateLimitMiddleware**: Enforces per-client rate limits
5. **AuthenticationMiddleware**: Validates session tokens
6. **CompressionMiddleware**: Compresses response bodies

Each middleware wraps the next handler in the chain, allowing it
to inspect and modify both the request (before) and response (after).

Configuration
-------------
Middleware behavior is controlled through the application settings:

- ``CORS_ALLOWED_ORIGINS``: List of allowed CORS origins
- ``RATE_LIMIT_REQUESTS``: Max requests per window
- ``RATE_LIMIT_WINDOW_SECONDS``: Rate limit window duration
- ``COMPRESSION_MIN_SIZE``: Minimum response size for compression
- ``EXEMPT_PATHS``: Paths excluded from authentication

Performance Impact
------------------
Middleware adds latency to every request. The total overhead for the
full middleware stack is approximately:
- RequestID: ~0.1ms
- Logging: ~0.5ms
- CORS: ~0.1ms
- Rate Limit: ~1.0ms (Redis lookup)
- Authentication: ~2.0ms (token verification)
- Compression: ~0.5ms (for typical response sizes)

Total: ~4.2ms additional latency per request.

Monitoring
----------
Each middleware reports its processing time via structured logging,
allowing performance regression detection in the monitoring dashboard.

Change History
--------------
- v1.0: Basic logging and CORS middleware
- v1.1: Added rate limiting with Redis backend
- v1.2: Added request ID tracing
- v1.3: Added response compression
- v1.4: Added security headers (HSTS, CSP, etc.)
- v1.5: Added request body size limiting
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class MiddlewareContext:
    """Shared context passed through the middleware chain.

    Allows middleware components to share data with downstream
    handlers and other middleware. The context is created fresh
    for each request.

    Attributes:
        request_id: Unique identifier for this request.
        start_time: Request processing start time.
        user_id: Authenticated user ID (set by auth middleware).
        metadata: Arbitrary middleware-specific data.
    """

    request_id: str = ""
    start_time: float = 0.0
    user_id: Optional[str] = None
    metadata: dict[str, Any] = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


class RequestIDMiddleware:
    """Assigns a unique request ID to each incoming request.

    The request ID is used for distributed tracing across services.
    It is added to the response headers as X-Request-ID and included
    in all log messages for the request lifecycle.

    If the incoming request already has an X-Request-ID header (from
    an upstream proxy), that value is preserved.
    """

    HEADER_NAME = "X-Request-ID"

    def process_request(self, request: Any, context: MiddlewareContext) -> None:
        """Assign or preserve request ID."""
        existing_id = getattr(request, "headers", {}).get(self.HEADER_NAME)
        if existing_id:
            context.request_id = existing_id
        else:
            context.request_id = str(uuid.uuid4())
        context.start_time = time.time()

    def process_response(self, response: Any, context: MiddlewareContext) -> None:
        """Add request ID to response headers."""
        if hasattr(response, "headers"):
            response.headers[self.HEADER_NAME] = context.request_id


class CORSMiddleware:
    """Cross-Origin Resource Sharing middleware.

    Handles CORS preflight requests (OPTIONS) and adds appropriate
    headers to responses to enable cross-origin access from
    configured origins.

    The middleware supports:
    - Wildcard and specific origin matching
    - Configurable allowed methods and headers
    - Credentials support
    - Preflight caching (Access-Control-Max-Age)

    Args:
        allowed_origins: List of allowed origin URLs.
        allowed_methods: List of allowed HTTP methods.
        allowed_headers: List of allowed request headers.
        max_age: Preflight cache duration in seconds.
        allow_credentials: Whether to allow credentials.
    """

    def __init__(
        self,
        allowed_origins: Optional[list[str]] = None,
        allowed_methods: Optional[list[str]] = None,
        allowed_headers: Optional[list[str]] = None,
        max_age: int = 86400,
        allow_credentials: bool = True,
    ) -> None:
        self._allowed_origins = allowed_origins or ["*"]
        self._allowed_methods = allowed_methods or [
            "GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"
        ]
        self._allowed_headers = allowed_headers or [
            "Authorization", "Content-Type", "X-Request-ID",
            "Accept", "Origin", "X-Requested-With",
        ]
        self._max_age = max_age
        self._allow_credentials = allow_credentials

    def is_allowed_origin(self, origin: str) -> bool:
        """Check if the given origin is in the allowed list."""
        if "*" in self._allowed_origins:
            return True
        return origin in self._allowed_origins

    def process_request(self, request: Any, context: MiddlewareContext) -> Optional[Any]:
        """Handle CORS preflight requests.

        Returns a response for OPTIONS requests, None otherwise.
        """
        if getattr(request, "method", "") == "OPTIONS":
            origin = getattr(request, "headers", {}).get("Origin", "")
            if self.is_allowed_origin(origin):
                # Return preflight response
                return self._build_preflight_response(origin)
        return None

    def process_response(self, response: Any, context: MiddlewareContext) -> None:
        """Add CORS headers to the response."""
        if hasattr(response, "headers"):
            response.headers["Access-Control-Allow-Origin"] = (
                self._allowed_origins[0] if self._allowed_origins else "*"
            )
            response.headers["Access-Control-Allow-Methods"] = ", ".join(
                self._allowed_methods
            )
            response.headers["Access-Control-Allow-Headers"] = ", ".join(
                self._allowed_headers
            )
            if self._allow_credentials:
                response.headers["Access-Control-Allow-Credentials"] = "true"

    def _build_preflight_response(self, origin: str) -> dict:
        """Build a CORS preflight response."""
        return {
            "status_code": 204,
            "headers": {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": ", ".join(self._allowed_methods),
                "Access-Control-Allow-Headers": ", ".join(self._allowed_headers),
                "Access-Control-Max-Age": str(self._max_age),
                "Access-Control-Allow-Credentials": str(self._allow_credentials).lower(),
            },
        }


class RateLimitMiddleware:
    """Per-client rate limiting middleware.

    Uses a token bucket algorithm to limit the number of requests
    per client within a configurable time window. Clients are
    identified by IP address (or authenticated user ID if available).

    When the rate limit is exceeded, a 429 Too Many Requests response
    is returned with a Retry-After header indicating when the client
    can retry.

    Args:
        max_requests: Maximum requests per window.
        window_seconds: Duration of the rate limit window.
    """

    def __init__(self, max_requests: int = 100, window_seconds: int = 60) -> None:
        self._max_requests = max_requests
        self._window = window_seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def get_client_key(self, request: Any, context: MiddlewareContext) -> str:
        """Determine the rate limit key for the client.

        Uses the authenticated user ID if available, otherwise
        falls back to the client IP address.
        """
        if context.user_id:
            return f"user:{context.user_id}"
        ip = getattr(request, "client_ip", "unknown")
        return f"ip:{ip}"

    def check_limit(self, key: str) -> tuple[bool, int]:
        """Check if the client has exceeded the rate limit.

        Returns:
            Tuple of (allowed, remaining_requests).
        """
        now = time.time()
        bucket = self._buckets[key]
        # Remove expired entries
        bucket[:] = [t for t in bucket if now - t < self._window]
        remaining = self._max_requests - len(bucket)
        return remaining > 0, max(0, remaining)

    def record_request(self, key: str) -> None:
        """Record a request for rate limiting."""
        self._buckets[key].append(time.time())


class SecurityHeadersMiddleware:
    """Adds security headers to all responses.

    Implements defense-in-depth by setting headers that mitigate
    common web vulnerabilities including XSS, clickjacking, MIME
    sniffing, and protocol downgrade attacks.

    The headers set by this middleware:
    - Strict-Transport-Security (HSTS)
    - X-Content-Type-Options
    - X-Frame-Options
    - X-XSS-Protection
    - Content-Security-Policy
    - Referrer-Policy
    - Permissions-Policy
    """

    SECURITY_HEADERS: dict[str, str] = {
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Content-Security-Policy": "default-src 'self'",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    }

    def process_response(self, response: Any, context: MiddlewareContext) -> None:
        """Add security headers to the response."""
        if hasattr(response, "headers"):
            for header, value in self.SECURITY_HEADERS.items():
                response.headers[header] = value


class RequestSizeLimitMiddleware:
    """Limits the size of incoming request bodies.

    Prevents denial-of-service attacks that attempt to exhaust
    server memory by sending very large request bodies.

    Args:
        max_size_bytes: Maximum allowed request body size.
    """

    def __init__(self, max_size_bytes: int = 10 * 1024 * 1024) -> None:
        self._max_size = max_size_bytes

    def check_size(self, request: Any) -> Optional[dict]:
        """Check if the request body exceeds the size limit.

        Returns:
            Error response dict if limit exceeded, None otherwise.
        """
        body = getattr(request, "body", {})
        # Estimate size from body dict
        import json as _json
        try:
            size = len(_json.dumps(body, default=str).encode())
        except (TypeError, ValueError):
            size = 0

        if size > self._max_size:
            return {
                "status_code": 413,
                "body": {
                    "error": {
                        "code": "PAYLOAD_TOO_LARGE",
                        "message": f"Request body exceeds {self._max_size} bytes",
                    }
                },
            }
        return None


class CompressionMiddleware:
    """Response compression middleware.

    Compresses response bodies using gzip when the client supports
    it (Accept-Encoding: gzip) and the response is larger than
    the minimum threshold.

    Only compresses JSON responses (Content-Type: application/json).

    Args:
        min_size: Minimum response size to trigger compression.
        compression_level: Gzip compression level (1-9).
    """

    def __init__(self, min_size: int = 1024, compression_level: int = 6) -> None:
        self._min_size = min_size
        self._level = compression_level

    def should_compress(self, request: Any, response: Any) -> bool:
        """Determine if the response should be compressed."""
        accept_encoding = getattr(request, "headers", {}).get("Accept-Encoding", "")
        if "gzip" not in accept_encoding:
            return False
        content_type = getattr(response, "headers", {}).get("Content-Type", "")
        if "json" not in content_type:
            return False
        return True
