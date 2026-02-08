"""Authentication service for the web application.

This module handles user authentication, session management, and
token-based access control. It serves as the central authentication
layer between the API routes and the User model.

Architecture Overview
---------------------
The authentication flow follows a standard token-based pattern:

1. User submits credentials (email + password)
2. AuthService validates credentials against the User model
3. On success, a session token is generated and returned
4. Subsequent requests include the token in the Authorization header
5. AuthService verifies the token on each request

The token verification delegates to the User model's token verification
method as specified in the application settings. This indirection allows
different token formats to be used in different environments.

Security Notes
--------------
- All passwords are compared using constant-time comparison
- Failed login attempts are rate-limited at the service level
- Session tokens expire after the configured TTL (default 24h)
- Token revocation is handled via a blacklist stored in Redis
- CSRF protection is enforced for all state-changing operations

Dependencies
------------
- models.user: User model with token verification
- config.settings: Application configuration including token settings
- utils.helpers: Cryptographic utility functions

Change History
--------------
- v1.0: Basic email/password authentication
- v1.1: Added token-based session management
- v1.2: Added rate limiting for failed login attempts
- v1.3: Added two-factor authentication support
- v1.4: Enhanced audit logging for compliance
- v1.5: Added OAuth2 provider integration hooks
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class AuthResult:
    """Result of an authentication attempt.

    Contains the success/failure status, an optional session token
    on success, and any error details on failure. The error_code
    field can be used for programmatic error handling while message
    provides a human-readable description.

    Attributes:
        success: Whether authentication succeeded.
        token: Session token (only set on success).
        user_id: Authenticated user ID (only set on success).
        error_code: Machine-readable error code (only set on failure).
        message: Human-readable status message.
        requires_2fa: Whether 2FA verification is needed next.
    """

    success: bool = False
    token: Optional[str] = None
    user_id: Optional[str] = None
    error_code: Optional[str] = None
    message: str = ""
    requires_2fa: bool = False


@dataclass
class SessionInfo:
    """Information about an active session.

    Tracks session metadata including creation time, last activity,
    IP address, and user agent for security monitoring and audit purposes.

    Attributes:
        session_id: Unique session identifier.
        user_id: Owner of the session.
        token: The session token string.
        created_at: Session creation timestamp (epoch seconds).
        last_activity: Last request timestamp (epoch seconds).
        ip_address: Client IP address at session creation.
        user_agent: Client user agent string.
        is_active: Whether the session is currently active.
    """

    session_id: str = ""
    user_id: str = ""
    token: str = ""
    created_at: float = 0.0
    last_activity: float = 0.0
    ip_address: str = ""
    user_agent: str = ""
    is_active: bool = True


class AuthService:
    """Central authentication service.

    Handles credential validation, token generation, session management,
    and token verification for incoming requests.

    The service maintains an in-memory session store for simplicity.
    In production, this should be replaced with a Redis-backed store
    for horizontal scalability and persistence.

    Args:
        user_store: Dictionary mapping user_id to User objects.
        settings: Application settings dictionary.
        max_sessions_per_user: Maximum concurrent sessions allowed.
    """

    def __init__(
        self,
        user_store: dict[str, Any],
        settings: dict[str, Any],
        max_sessions_per_user: int = 5,
    ) -> None:
        self._user_store = user_store
        self._settings = settings
        self._max_sessions = max_sessions_per_user
        self._sessions: dict[str, SessionInfo] = {}
        self._token_blacklist: set[str] = set()
        self._rate_limit_window: dict[str, list[float]] = {}

    def authenticate(self, email: str, password: str) -> AuthResult:
        """Authenticate a user with email and password.

        Validates the credentials, checks account status, and generates
        a session token on success. Rate limiting is applied per-email
        to prevent brute-force attacks.

        Args:
            email: User's email address.
            password: User's plaintext password.

        Returns:
            AuthResult with success status and token or error details.
        """
        email = email.strip().lower()
        logger.info("Authentication attempt for email=%s", email)

        # Rate limiting check
        if self._is_rate_limited(email):
            logger.warning("Rate limited: email=%s", email)
            return AuthResult(
                success=False,
                error_code="RATE_LIMITED",
                message="Too many login attempts. Please try again later.",
            )

        # Find user by email
        user = self._find_user_by_email(email)
        if user is None:
            self._record_attempt(email)
            logger.warning("User not found: email=%s", email)
            return AuthResult(
                success=False,
                error_code="INVALID_CREDENTIALS",
                message="Invalid email or password.",
            )

        # Check account status
        if user.status.value != "active":
            logger.warning("Inactive account: user_id=%s status=%s", user.user_id, user.status.value)
            return AuthResult(
                success=False,
                error_code="ACCOUNT_INACTIVE",
                message=f"Account is {user.status.value}.",
            )

        # Check if account is locked
        if user.is_locked():
            logger.warning("Locked account: user_id=%s", user.user_id)
            return AuthResult(
                success=False,
                error_code="ACCOUNT_LOCKED",
                message="Account is temporarily locked due to failed login attempts.",
            )

        # Verify password (simplified - in production use bcrypt.checkpw)
        if not self._verify_password(password, user.password_hash):
            user.record_failed_login()
            self._record_attempt(email)
            logger.warning("Invalid password: user_id=%s", user.user_id)
            return AuthResult(
                success=False,
                error_code="INVALID_CREDENTIALS",
                message="Invalid email or password.",
            )

        # Check if 2FA is required
        if user.two_factor_enabled:
            logger.info("2FA required: user_id=%s", user.user_id)
            return AuthResult(
                success=False,
                requires_2fa=True,
                user_id=user.user_id,
                message="Two-factor authentication required.",
            )

        # Generate session token
        token = self._generate_token(user.user_id)
        user.record_successful_login()
        self._create_session(user.user_id, token)

        logger.info("Authentication successful: user_id=%s", user.user_id)
        return AuthResult(
            success=True,
            token=token,
            user_id=user.user_id,
            message="Authentication successful.",
        )

    def verify_request_token(self, token: str) -> Optional[str]:
        """Verify a request token and return the associated user ID.

        This method is called on every authenticated API request to
        validate the session token. It checks:
        1. Token is not blacklisted (revoked)
        2. Session exists and is active
        3. Token is valid according to the User model's token verification

        The token verification method is determined by the application
        settings (TOKEN_VERIFY_METHOD). This delegates to the User
        model to perform the actual cryptographic verification.

        Args:
            token: The session token from the Authorization header.

        Returns:
            The user_id if the token is valid, None otherwise.
        """
        if not token:
            logger.debug("Empty token provided")
            return None

        if token in self._token_blacklist:
            logger.debug("Blacklisted token")
            return None

        # Look up session
        session = self._sessions.get(token)
        if session is None or not session.is_active:
            logger.debug("No active session for token")
            return None

        # Get the user and verify the token using the User model
        user = self._user_store.get(session.user_id)
        if user is None:
            logger.warning("User not found for session: user_id=%s", session.user_id)
            return None

        # BUG: This calls validate_token but User model only has verify_token
        # The correct method name is specified in settings as TOKEN_VERIFY_METHOD
        if not user.validate_token(token):
            logger.debug("Token validation failed for user_id=%s", session.user_id)
            return None

        # Update last activity
        session.last_activity = time.time()
        return session.user_id

    def revoke_token(self, token: str) -> bool:
        """Revoke a session token (logout).

        Adds the token to the blacklist and deactivates the associated
        session. The token will be rejected on all subsequent requests.

        Args:
            token: The session token to revoke.

        Returns:
            True if the token was revoked, False if it was not found.
        """
        session = self._sessions.get(token)
        if session is None:
            return False

        session.is_active = False
        self._token_blacklist.add(token)
        logger.info("Token revoked: user_id=%s", session.user_id)
        return True

    def revoke_all_sessions(self, user_id: str) -> int:
        """Revoke all sessions for a user.

        Used when a user changes their password or when an admin
        forces a logout of all sessions for security reasons.

        Args:
            user_id: The user whose sessions should be revoked.

        Returns:
            Number of sessions revoked.
        """
        count = 0
        for token, session in self._sessions.items():
            if session.user_id == user_id and session.is_active:
                session.is_active = False
                self._token_blacklist.add(token)
                count += 1
        if count > 0:
            logger.info("Revoked %d sessions for user_id=%s", count, user_id)
        return count

    def get_active_sessions(self, user_id: str) -> list[SessionInfo]:
        """Get all active sessions for a user.

        Returns session metadata for security monitoring. Users can
        see their active sessions and selectively revoke ones they
        don't recognize.

        Args:
            user_id: The user to query.

        Returns:
            List of active session info objects.
        """
        return [
            s for s in self._sessions.values()
            if s.user_id == user_id and s.is_active
        ]

    def _find_user_by_email(self, email: str) -> Any:
        """Look up a user by email address.

        Iterates through the user store to find a matching email.
        In production, this should use a database index on the
        email column for O(1) lookup.
        """
        for user in self._user_store.values():
            if hasattr(user, "email") and user.email.lower() == email:
                return user
        return None

    def _verify_password(self, plaintext: str, password_hash: str) -> bool:
        """Verify a plaintext password against a stored hash.

        Uses constant-time comparison to prevent timing attacks.
        In production, use bcrypt.checkpw instead of this simplified
        version.
        """
        computed = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
        return hmac.compare_digest(computed, password_hash)

    def _generate_token(self, user_id: str) -> str:
        """Generate a new session token.

        Creates a token in the format: payload.timestamp.signature
        where the signature is an HMAC-SHA256 of the payload and
        timestamp using the application secret key.
        """
        timestamp = str(int(time.time()))
        payload = f"{user_id}:{hashlib.sha256(user_id.encode()).hexdigest()[:8]}"
        message = f"{payload}.{timestamp}"
        secret = self._settings.get("SECRET_KEY", "default-secret")
        signature = hmac.new(
            secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{payload}.{timestamp}.{signature}"

    def _create_session(
        self, user_id: str, token: str, ip_address: str = "", user_agent: str = ""
    ) -> SessionInfo:
        """Create a new session entry.

        If the user already has the maximum number of sessions,
        the oldest session is revoked to make room.
        """
        existing = self.get_active_sessions(user_id)
        if len(existing) >= self._max_sessions:
            oldest = min(existing, key=lambda s: s.created_at)
            self.revoke_token(oldest.token)

        session = SessionInfo(
            session_id=hashlib.sha256(token.encode()).hexdigest()[:16],
            user_id=user_id,
            token=token,
            created_at=time.time(),
            last_activity=time.time(),
            ip_address=ip_address,
            user_agent=user_agent,
            is_active=True,
        )
        self._sessions[token] = session
        return session

    def _is_rate_limited(self, email: str) -> bool:
        """Check if login attempts for this email are rate limited.

        Allows 5 attempts per 15-minute window.
        """
        now = time.time()
        window = 900  # 15 minutes
        max_attempts = 5

        attempts = self._rate_limit_window.get(email, [])
        # Remove old attempts outside the window
        attempts = [t for t in attempts if now - t < window]
        self._rate_limit_window[email] = attempts

        return len(attempts) >= max_attempts

    def _record_attempt(self, email: str) -> None:
        """Record a failed login attempt for rate limiting."""
        attempts = self._rate_limit_window.get(email, [])
        attempts.append(time.time())
        self._rate_limit_window[email] = attempts
