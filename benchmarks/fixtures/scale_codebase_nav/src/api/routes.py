"""API route definitions for the web service.

This module defines the HTTP endpoint handlers for the application's
REST API. Each route handler delegates to the appropriate service layer
for business logic execution.

API Versioning
--------------
The API uses URL path versioning (e.g., /api/v1/...). Breaking changes
require a new version, while backward-compatible additions can be made
to the existing version.

Authentication
--------------
All endpoints except /auth/login and /health require a valid session
token in the Authorization header using the Bearer scheme:
    Authorization: Bearer <token>

Rate Limiting
-------------
API rate limits are enforced per-user and per-endpoint:
- Standard endpoints: 100 requests/minute
- Auth endpoints: 10 requests/minute
- Search endpoints: 30 requests/minute
- Bulk endpoints: 5 requests/minute

Error Response Format
---------------------
All error responses follow a standard format::

    {
        "error": {
            "code": "MACHINE_READABLE_CODE",
            "message": "Human-readable description",
            "details": { ... }
        }
    }

CORS Configuration
------------------
Cross-origin requests are allowed from configured origins with
credentials. The allowed origins are specified in the application
settings under CORS_ALLOWED_ORIGINS.

Content Negotiation
-------------------
The API supports JSON (application/json) as the primary content type.
Some endpoints also support CSV export via the Accept header or a
format query parameter.

Change History
--------------
- v1.0: Initial API with auth and order endpoints
- v1.1: Added user profile management endpoints
- v1.2: Added admin endpoints for user and order management
- v1.3: Added search and filtering on list endpoints
- v1.4: Added bulk operations endpoints
- v1.5: Added webhook configuration endpoints
- v1.6: Added health and readiness probes
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class Request:
    """Simplified HTTP request object.

    Represents an incoming HTTP request with method, path, headers,
    query parameters, and body. This is a simplified version for
    the fixture -- in production, the web framework provides this.

    Attributes:
        method: HTTP method (GET, POST, PUT, DELETE, PATCH).
        path: Request URL path.
        headers: Request headers as key-value pairs.
        query_params: Query string parameters.
        body: Parsed request body (from JSON).
        client_ip: Client IP address.
    """

    method: str = "GET"
    path: str = "/"
    headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)
    client_ip: str = "127.0.0.1"

    @property
    def auth_token(self) -> Optional[str]:
        """Extract Bearer token from Authorization header."""
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        return None


@dataclass
class Response:
    """Simplified HTTP response object.

    Attributes:
        status_code: HTTP status code.
        body: Response body (will be JSON serialized).
        headers: Response headers.
    """

    status_code: int = 200
    body: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=lambda: {
        "Content-Type": "application/json"
    })

    def to_json(self) -> str:
        """Serialize response body to JSON."""
        return json.dumps(self.body, indent=2, default=str)


class Router:
    """Simple URL router for matching requests to handlers.

    Supports path parameters using {param_name} syntax.
    Routes are matched in registration order (first match wins).

    Attributes:
        routes: Registered route handlers.
        middleware: Global middleware functions.
    """

    def __init__(self) -> None:
        self.routes: list[tuple[str, str, Callable]] = []
        self.middleware: list[Callable] = []

    def get(self, path: str) -> Callable:
        """Register a GET route handler."""
        def decorator(func: Callable) -> Callable:
            self.routes.append(("GET", path, func))
            return func
        return decorator

    def post(self, path: str) -> Callable:
        """Register a POST route handler."""
        def decorator(func: Callable) -> Callable:
            self.routes.append(("POST", path, func))
            return func
        return decorator

    def put(self, path: str) -> Callable:
        """Register a PUT route handler."""
        def decorator(func: Callable) -> Callable:
            self.routes.append(("PUT", path, func))
            return func
        return decorator

    def delete(self, path: str) -> Callable:
        """Register a DELETE route handler."""
        def decorator(func: Callable) -> Callable:
            self.routes.append(("DELETE", path, func))
            return func
        return decorator

    def match(self, method: str, path: str) -> Optional[tuple[Callable, dict[str, str]]]:
        """Find a matching route handler for the given method and path.

        Returns:
            Tuple of (handler, path_params) or None if no match.
        """
        for route_method, route_path, handler in self.routes:
            if route_method != method:
                continue
            params = self._match_path(route_path, path)
            if params is not None:
                return handler, params
        return None

    @staticmethod
    def _match_path(pattern: str, path: str) -> Optional[dict[str, str]]:
        """Match a URL path against a pattern with {param} placeholders."""
        pattern_parts = pattern.strip("/").split("/")
        path_parts = path.strip("/").split("/")

        if len(pattern_parts) != len(path_parts):
            return None

        params: dict[str, str] = {}
        for pp, rp in zip(pattern_parts, path_parts):
            if pp.startswith("{") and pp.endswith("}"):
                params[pp[1:-1]] = rp
            elif pp != rp:
                return None
        return params


class APIRoutes:
    """API route handlers for the web service.

    Wires up all route handlers with the service layer and provides
    the main request dispatch method.

    Args:
        auth_service: Authentication service.
        order_service: Order management service.
        notification_service: Notification service.
    """

    def __init__(
        self,
        auth_service: Any,
        order_service: Any,
        notification_service: Any,
    ) -> None:
        self._auth = auth_service
        self._orders = order_service
        self._notifications = notification_service
        self._router = Router()
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Register all API routes."""

        @self._router.post("/api/v1/auth/login")
        def login(req: Request, params: dict) -> Response:
            email = req.body.get("email", "")
            password = req.body.get("password", "")
            result = self._auth.authenticate(email, password)
            if result.success:
                return Response(
                    status_code=200,
                    body={"token": result.token, "user_id": result.user_id},
                )
            return Response(
                status_code=401,
                body={"error": {"code": result.error_code, "message": result.message}},
            )

        @self._router.post("/api/v1/auth/logout")
        def logout(req: Request, params: dict) -> Response:
            token = req.auth_token
            if not token:
                return Response(status_code=401, body={"error": {"code": "NO_TOKEN"}})
            self._auth.revoke_token(token)
            return Response(status_code=200, body={"message": "Logged out"})

        @self._router.post("/api/v1/orders")
        def create_order(req: Request, params: dict) -> Response:
            token = req.auth_token
            if not token:
                return Response(status_code=401, body={"error": {"code": "NO_TOKEN"}})
            result = self._orders.create_order(
                token=token,
                items=req.body.get("items", []),
                shipping_info=req.body.get("shipping", {}),
                coupon_code=req.body.get("coupon_code"),
            )
            if result.success:
                return Response(status_code=201, body={"order": result.order})
            return Response(
                status_code=400,
                body={"error": {"code": result.error_code, "message": result.message}},
            )

        @self._router.get("/api/v1/orders")
        def list_orders(req: Request, params: dict) -> Response:
            token = req.auth_token
            if not token:
                return Response(status_code=401, body={"error": {"code": "NO_TOKEN"}})
            page = int(req.query_params.get("page", "1"))
            page_size = int(req.query_params.get("page_size", "20"))
            status = req.query_params.get("status")
            result = self._orders.list_orders(token, page, page_size, status)
            if result.success:
                return Response(status_code=200, body=result.data)
            return Response(
                status_code=400,
                body={"error": {"code": result.error_code, "message": result.message}},
            )

        @self._router.get("/api/v1/orders/{order_id}")
        def get_order(req: Request, params: dict) -> Response:
            token = req.auth_token
            if not token:
                return Response(status_code=401, body={"error": {"code": "NO_TOKEN"}})
            result = self._orders.get_order(token, params["order_id"])
            if result.success:
                return Response(status_code=200, body={"order": result.order})
            status_map = {"NOT_FOUND": 404, "FORBIDDEN": 403}
            return Response(
                status_code=status_map.get(result.error_code, 400),
                body={"error": {"code": result.error_code, "message": result.message}},
            )

        @self._router.put("/api/v1/orders/{order_id}/cancel")
        def cancel_order(req: Request, params: dict) -> Response:
            token = req.auth_token
            if not token:
                return Response(status_code=401, body={"error": {"code": "NO_TOKEN"}})
            result = self._orders.cancel_order(token, params["order_id"])
            if result.success:
                return Response(status_code=200, body={"order": result.order})
            return Response(
                status_code=400,
                body={"error": {"code": result.error_code, "message": result.message}},
            )

        @self._router.get("/api/v1/health")
        def health(req: Request, params: dict) -> Response:
            return Response(
                status_code=200,
                body={"status": "healthy", "timestamp": time.time()},
            )

    def dispatch(self, request: Request) -> Response:
        """Dispatch an incoming request to the appropriate handler.

        Applies middleware, finds the matching route, and executes
        the handler. Returns a 404 response if no route matches.

        Args:
            request: The incoming HTTP request.

        Returns:
            The HTTP response.
        """
        start_time = time.time()
        logger.info(
            "Request: method=%s path=%s ip=%s",
            request.method, request.path, request.client_ip,
        )

        match = self._router.match(request.method, request.path)
        if match is None:
            return Response(
                status_code=404,
                body={"error": {"code": "NOT_FOUND", "message": "Endpoint not found"}},
            )

        handler, params = match
        try:
            response = handler(request, params)
        except Exception as exc:
            logger.exception("Unhandled error in %s %s", request.method, request.path)
            response = Response(
                status_code=500,
                body={"error": {"code": "INTERNAL_ERROR", "message": str(exc)}},
            )

        elapsed = time.time() - start_time
        logger.info(
            "Response: status=%d elapsed=%.3fs",
            response.status_code, elapsed,
        )
        return response
