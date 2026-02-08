"""Tests for the authentication service.

This test module covers the core authentication functionality including
credential validation, token generation, session management, rate limiting,
and token verification. Each test case is documented with its purpose
and expected behavior.

Test Strategy
-------------
Tests use in-memory stores and mock objects to isolate the auth service
from external dependencies. The User model is instantiated directly
with known values to make assertions predictable.

The test structure follows the Arrange-Act-Assert pattern:
1. Set up test fixtures and dependencies
2. Call the method under test
3. Verify the result and side effects

Test Categories
---------------
1. **Authentication Tests**: Login flow with valid/invalid credentials
2. **Token Tests**: Token generation, verification, and expiration
3. **Session Tests**: Session creation, listing, and revocation
4. **Rate Limiting Tests**: Per-email rate limiting enforcement
5. **Edge Case Tests**: Boundary conditions and error handling

Coverage Goals
--------------
- Line coverage: >90%
- Branch coverage: >85%
- All error paths tested
- All state transitions tested

Change History
--------------
- v1.0: Basic auth tests
- v1.1: Added session management tests
- v1.2: Added rate limiting tests
- v1.3: Added 2FA verification tests
- v1.4: Added concurrent session limit tests
"""

from __future__ import annotations

import hashlib
import hmac
import time
from unittest.mock import MagicMock, patch

# Fixtures and helpers for test setup


def make_user(
    user_id: str = "user-001",
    email: str = "test@example.com",
    password: str = "password123",
    status: str = "active",
    two_factor: bool = False,
):
    """Create a test user with known credentials.

    The password is hashed using SHA-256 for simplicity in tests.
    The User model's verify_token method is the canonical way to
    check authentication tokens.

    Args:
        user_id: Unique user identifier.
        email: User email address.
        password: Plaintext password (will be hashed).
        status: Account status string.
        two_factor: Whether 2FA is enabled.

    Returns:
        A mock User object with the specified attributes.
    """
    password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    user = MagicMock()
    user.user_id = user_id
    user.email = email
    user.password_hash = password_hash
    user.status = MagicMock(value=status)
    user.two_factor_enabled = two_factor
    user.two_factor_secret = "TESTSECRET" if two_factor else None
    user.login_attempts = 0
    user.locked_until = None
    user.is_locked.return_value = False

    # verify_token is the correct method name per settings.py
    user.verify_token.return_value = True

    return user


def make_auth_service(users=None, settings=None):
    """Create an AuthService instance with test configuration.

    Args:
        users: Dict mapping user_id to User objects.
        settings: Application settings dict.

    Returns:
        Configured AuthService instance.
    """
    from scale_codebase_nav.src.services.auth import AuthService

    if users is None:
        users = {}
    if settings is None:
        settings = {
            "SECRET_KEY": "test-secret",
            "TOKEN_VERIFY_METHOD": "verify_token",
        }
    return AuthService(
        user_store=users,
        settings=settings,
    )


# ── Authentication Tests ───────────────────────────────────────────────────


class TestAuthentication:
    """Test the login authentication flow."""

    def test_successful_login(self):
        """A valid email and password should return a token.

        The authenticate method should:
        1. Find the user by email
        2. Verify the password hash
        3. Generate a session token
        4. Record the successful login
        """
        user = make_user()
        service = make_auth_service(users={user.user_id: user})
        result = service.authenticate("test@example.com", "password123")
        assert result.success
        assert result.token is not None
        assert result.user_id == "user-001"

    def test_invalid_email(self):
        """An unknown email should return INVALID_CREDENTIALS.

        The error message should not reveal whether the email
        exists in the system (to prevent enumeration).
        """
        service = make_auth_service()
        result = service.authenticate("unknown@example.com", "password123")
        assert not result.success
        assert result.error_code == "INVALID_CREDENTIALS"

    def test_invalid_password(self):
        """A wrong password should return INVALID_CREDENTIALS."""
        user = make_user()
        service = make_auth_service(users={user.user_id: user})
        result = service.authenticate("test@example.com", "wrong-password")
        assert not result.success
        assert result.error_code == "INVALID_CREDENTIALS"

    def test_inactive_account(self):
        """A suspended account should return ACCOUNT_INACTIVE."""
        user = make_user(status="suspended")
        service = make_auth_service(users={user.user_id: user})
        result = service.authenticate("test@example.com", "password123")
        assert not result.success
        assert result.error_code == "ACCOUNT_INACTIVE"

    def test_locked_account(self):
        """A locked account should return ACCOUNT_LOCKED."""
        user = make_user()
        user.is_locked.return_value = True
        service = make_auth_service(users={user.user_id: user})
        result = service.authenticate("test@example.com", "password123")
        assert not result.success
        assert result.error_code == "ACCOUNT_LOCKED"

    def test_two_factor_required(self):
        """An account with 2FA should require additional verification.

        The initial authentication should succeed but indicate that
        2FA is needed before a full session is created.
        """
        user = make_user(two_factor=True)
        service = make_auth_service(users={user.user_id: user})
        result = service.authenticate("test@example.com", "password123")
        assert not result.success
        assert result.requires_2fa


# ── Token Verification Tests ──────────────────────────────────────────────


class TestTokenVerification:
    """Test token verification in request handling.

    The auth service delegates to the User model's verify_token method
    for cryptographic token verification. This ensures the correct
    method is called on the user object.
    """

    def test_valid_token_returns_user_id(self):
        """A valid token should return the associated user ID.

        The verify_request_token method should:
        1. Check the token is not blacklisted
        2. Find the session for this token
        3. Call user.verify_token(token) to verify
        4. Return the user_id on success
        """
        user = make_user()
        service = make_auth_service(users={user.user_id: user})
        auth_result = service.authenticate("test@example.com", "password123")
        token = auth_result.token

        user_id = service.verify_request_token(token)
        # Note: This will fail because auth.py calls validate_token
        # instead of verify_token. The fix is to change auth.py to
        # call user.verify_token(token) as specified in settings.py
        assert user_id == "user-001"

    def test_empty_token(self):
        """An empty token should return None."""
        service = make_auth_service()
        assert service.verify_request_token("") is None

    def test_blacklisted_token(self):
        """A revoked token should return None."""
        user = make_user()
        service = make_auth_service(users={user.user_id: user})
        result = service.authenticate("test@example.com", "password123")
        service.revoke_token(result.token)
        assert service.verify_request_token(result.token) is None


# ── Session Management Tests ──────────────────────────────────────────────


class TestSessionManagement:
    """Test session creation, listing, and revocation."""

    def test_session_created_on_login(self):
        """A successful login should create a session."""
        user = make_user()
        service = make_auth_service(users={user.user_id: user})
        service.authenticate("test@example.com", "password123")
        sessions = service.get_active_sessions(user.user_id)
        assert len(sessions) == 1

    def test_multiple_sessions(self):
        """Multiple logins should create separate sessions."""
        user = make_user()
        service = make_auth_service(users={user.user_id: user})
        service.authenticate("test@example.com", "password123")
        service.authenticate("test@example.com", "password123")
        sessions = service.get_active_sessions(user.user_id)
        assert len(sessions) == 2

    def test_session_limit(self):
        """Exceeding session limit should revoke oldest session."""
        user = make_user()
        service = make_auth_service(
            users={user.user_id: user},
            settings={"SECRET_KEY": "test", "TOKEN_VERIFY_METHOD": "verify_token"},
        )
        service._max_sessions = 2
        service.authenticate("test@example.com", "password123")
        service.authenticate("test@example.com", "password123")
        service.authenticate("test@example.com", "password123")
        sessions = service.get_active_sessions(user.user_id)
        assert len(sessions) <= 2

    def test_revoke_all_sessions(self):
        """Revoking all sessions should deactivate everything."""
        user = make_user()
        service = make_auth_service(users={user.user_id: user})
        service.authenticate("test@example.com", "password123")
        service.authenticate("test@example.com", "password123")
        count = service.revoke_all_sessions(user.user_id)
        assert count == 2
        sessions = service.get_active_sessions(user.user_id)
        assert len(sessions) == 0


# ── Rate Limiting Tests ───────────────────────────────────────────────────


class TestRateLimiting:
    """Test login rate limiting.

    The auth service limits failed login attempts per email to prevent
    brute-force attacks. After exceeding the limit, further attempts
    are rejected without checking credentials.
    """

    def test_rate_limit_after_max_attempts(self):
        """Should rate limit after too many failed attempts.

        The default limit is 5 attempts per 15-minute window.
        After 5 failures, the 6th attempt should be rate limited.
        """
        service = make_auth_service()
        for _ in range(5):
            service.authenticate("attacker@example.com", "wrong")

        result = service.authenticate("attacker@example.com", "wrong")
        assert result.error_code == "RATE_LIMITED"

    def test_different_emails_not_affected(self):
        """Rate limiting is per-email, not global."""
        service = make_auth_service()
        for _ in range(5):
            service.authenticate("attacker@example.com", "wrong")

        result = service.authenticate("legitimate@example.com", "wrong")
        assert result.error_code != "RATE_LIMITED"
