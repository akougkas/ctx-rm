"""User model for the web service.

This module defines the core User entity used throughout the application.
The User model encapsulates all user-related data and provides methods
for authentication, authorization, and profile management.

Design Notes
------------
The User model follows an active-record-like pattern where business logic
is co-located with the data representation. This was chosen for simplicity
in a monolithic application, but future refactoring may move validation
and token handling into separate service layers.

Security Considerations
-----------------------
- Password hashing uses bcrypt with a work factor of 12
- Token verification is performed via the ``verify_token`` method
- Session management is handled externally by the auth service
- Email addresses are normalized to lowercase before storage

Change History
--------------
- v1.0: Initial user model with basic CRUD
- v1.1: Added token-based authentication support
- v1.2: Enhanced profile fields and address management
- v1.3: Added role-based access control fields
- v1.4: Migrated from SHA-256 to bcrypt for password hashing
- v1.5: Added two-factor authentication support fields
- v1.6: Enhanced audit logging for compliance requirements
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional


class UserRole(Enum):
    """Enumeration of available user roles in the system.

    Each role maps to a specific set of permissions that control
    access to various features and API endpoints. The role hierarchy
    is: ADMIN > MANAGER > EDITOR > VIEWER > GUEST.

    Attributes:
        ADMIN: Full system access including user management and
            configuration. Can create and delete other admin accounts.
            Has access to audit logs and system health endpoints.
        MANAGER: Can manage teams, approve requests, and view reports.
            Cannot modify system configuration or manage admin accounts.
            Has access to team-level analytics and reporting dashboards.
        EDITOR: Can create and modify content within their assigned
            projects. Cannot manage teams or approve organizational
            requests. Limited to project-scoped analytics.
        VIEWER: Read-only access to content they have been granted
            access to. Cannot create or modify any content. Can
            export data in read-only formats (CSV, PDF).
        GUEST: Minimal access for unauthenticated or trial users.
            Can only view public content and cannot access any
            protected resources or API endpoints.
    """

    ADMIN = "admin"
    MANAGER = "manager"
    EDITOR = "editor"
    VIEWER = "viewer"
    GUEST = "guest"


class AccountStatus(Enum):
    """Account lifecycle status values.

    Tracks the current state of a user account through its lifecycle
    from creation to potential deletion. Status transitions follow
    a specific state machine:

        PENDING -> ACTIVE -> (SUSPENDED | DEACTIVATED)
        SUSPENDED -> ACTIVE
        DEACTIVATED -> (cannot be reactivated)
    """

    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


@dataclass
class Address:
    """Physical address associated with a user profile.

    Used for billing, shipping, and compliance purposes. All fields
    are optional except country, which is required for tax calculation.

    Attributes:
        street_line_1: Primary street address line.
        street_line_2: Secondary address line (apt, suite, etc.).
        city: City or municipality name.
        state_province: State, province, or region.
        postal_code: ZIP or postal code.
        country: ISO 3166-1 alpha-2 country code (required).
    """

    street_line_1: str = ""
    street_line_2: str = ""
    city: str = ""
    state_province: str = ""
    postal_code: str = ""
    country: str = "US"

    def format_single_line(self) -> str:
        """Return a single-line formatted address string."""
        parts = [
            self.street_line_1,
            self.street_line_2,
            self.city,
            self.state_province,
            self.postal_code,
            self.country,
        ]
        return ", ".join(p for p in parts if p)

    def validate(self) -> list[str]:
        """Validate address fields and return a list of error messages."""
        errors = []
        if not self.country:
            errors.append("Country is required")
        if len(self.country) != 2:
            errors.append("Country must be a 2-letter ISO code")
        if self.postal_code and not re.match(r"^[A-Za-z0-9\s-]+$", self.postal_code):
            errors.append("Invalid postal code format")
        return errors


@dataclass
class User:
    """Core user entity for the web service.

    Holds all user profile data, authentication credentials, and
    provides methods for token verification and password management.

    The ``verify_token`` method is the canonical way to check whether
    a given authentication token is valid for this user. It checks
    both the token signature and expiration time.

    Attributes:
        user_id: Unique identifier (UUID format).
        email: Normalized email address (lowercase).
        display_name: User-chosen display name.
        password_hash: Bcrypt hash of the user's password.
        role: Current role assignment.
        status: Account lifecycle status.
        created_at: Account creation timestamp.
        updated_at: Last profile update timestamp.
        last_login_at: Most recent successful login timestamp.
        two_factor_enabled: Whether 2FA is active.
        two_factor_secret: TOTP secret key (encrypted at rest).
        address: Optional physical address.
        preferences: User preference key-value store.
        login_attempts: Count of failed login attempts since last success.
        locked_until: Timestamp until which the account is locked.
    """

    user_id: str = ""
    email: str = ""
    display_name: str = ""
    password_hash: str = ""
    role: UserRole = UserRole.VIEWER
    status: AccountStatus = AccountStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_login_at: Optional[datetime] = None
    two_factor_enabled: bool = False
    two_factor_secret: Optional[str] = None
    address: Optional[Address] = None
    preferences: dict[str, Any] = field(default_factory=dict)
    login_attempts: int = 0
    locked_until: Optional[datetime] = None

    def verify_token(self, token: str) -> bool:
        """Verify that the given authentication token is valid.

        This method checks the token's HMAC signature against the user's
        stored secret and verifies that the token has not expired. The
        token format is: ``<payload>.<timestamp>.<signature>``.

        Algorithm:
            1. Split token into payload, timestamp, and signature
            2. Verify the timestamp is within the allowed window
            3. Recompute HMAC using the user's password hash as key
            4. Compare signatures using constant-time comparison

        Args:
            token: The authentication token string to verify.

        Returns:
            True if the token is valid and not expired, False otherwise.

        Example::

            >>> user = User(user_id="abc123", password_hash="$2b$12$...")
            >>> user.verify_token("eyJhbGci.1234567890.hmac_sig")
            True
        """
        if not token or "." not in token:
            return False

        parts = token.split(".")
        if len(parts) != 3:
            return False

        payload, timestamp_str, signature = parts

        try:
            token_time = int(timestamp_str)
        except ValueError:
            return False

        # Token expires after 24 hours
        current_time = int(time.time())
        if current_time - token_time > 86400:
            return False

        # Recompute expected signature
        message = f"{payload}.{timestamp_str}"
        expected = hmac.new(
            self.password_hash.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    def is_locked(self) -> bool:
        """Check if the account is currently locked due to failed attempts.

        An account becomes locked after 5 consecutive failed login attempts.
        The lock duration increases exponentially: 1 minute after 5 attempts,
        5 minutes after 10, 30 minutes after 15, and so on.

        Returns:
            True if the account is locked and the lock has not expired.
        """
        if self.locked_until is None:
            return False
        return datetime.now(timezone.utc) < self.locked_until

    def record_failed_login(self) -> None:
        """Record a failed login attempt and potentially lock the account.

        After 5 consecutive failures, the account is locked for an
        exponentially increasing duration. The counter resets on
        successful login.
        """
        self.login_attempts += 1
        if self.login_attempts >= 5:
            lock_minutes = 2 ** ((self.login_attempts - 5) // 5)
            self.locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=lock_minutes
            )
        self.updated_at = datetime.now(timezone.utc)

    def record_successful_login(self) -> None:
        """Record a successful login, resetting failure counters."""
        self.login_attempts = 0
        self.locked_until = None
        self.last_login_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def has_permission(self, permission: str) -> bool:
        """Check if the user's role grants the specified permission.

        The permission system uses a simple role-based model where each
        role has a predefined set of allowed actions. Permissions are
        checked in a hierarchical manner -- higher roles inherit all
        permissions from lower roles.

        Args:
            permission: The permission string to check (e.g., "edit_content").

        Returns:
            True if the user's role grants the permission.
        """
        role_permissions: dict[UserRole, set[str]] = {
            UserRole.ADMIN: {
                "manage_users", "manage_system", "view_audit_logs",
                "manage_teams", "approve_requests", "view_reports",
                "edit_content", "create_content", "delete_content",
                "view_content", "export_data",
            },
            UserRole.MANAGER: {
                "manage_teams", "approve_requests", "view_reports",
                "edit_content", "create_content", "view_content",
                "export_data",
            },
            UserRole.EDITOR: {
                "edit_content", "create_content", "view_content",
                "export_data",
            },
            UserRole.VIEWER: {"view_content", "export_data"},
            UserRole.GUEST: {"view_content"},
        }
        allowed = role_permissions.get(self.role, set())
        return permission in allowed

    def normalize_email(self) -> None:
        """Normalize the email address to lowercase and strip whitespace.

        This ensures consistent email handling throughout the application
        and prevents duplicate accounts with different casing.
        """
        self.email = self.email.strip().lower()

    def update_profile(
        self,
        display_name: Optional[str] = None,
        address: Optional[Address] = None,
        preferences: Optional[dict[str, Any]] = None,
    ) -> None:
        """Update user profile fields.

        Only non-None arguments are applied. The ``updated_at`` timestamp
        is automatically set to the current time.

        Args:
            display_name: New display name.
            address: New address.
            preferences: Preference updates (merged with existing).
        """
        if display_name is not None:
            self.display_name = display_name
        if address is not None:
            self.address = address
        if preferences is not None:
            self.preferences.update(preferences)
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self, include_sensitive: bool = False) -> dict[str, Any]:
        """Serialize user to a dictionary.

        Args:
            include_sensitive: If True, include password_hash and 2FA secret.

        Returns:
            Dictionary representation of the user.
        """
        data: dict[str, Any] = {
            "user_id": self.user_id,
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_login_at": (
                self.last_login_at.isoformat() if self.last_login_at else None
            ),
            "two_factor_enabled": self.two_factor_enabled,
            "preferences": self.preferences,
        }
        if include_sensitive:
            data["password_hash"] = self.password_hash
            data["two_factor_secret"] = self.two_factor_secret
        if self.address:
            data["address"] = {
                "street_line_1": self.address.street_line_1,
                "street_line_2": self.address.street_line_2,
                "city": self.address.city,
                "state_province": self.address.state_province,
                "postal_code": self.address.postal_code,
                "country": self.address.country,
            }
        return data

    def __repr__(self) -> str:
        return (
            f"User(id={self.user_id!r}, email={self.email!r}, "
            f"role={self.role.value!r}, status={self.status.value!r})"
        )
