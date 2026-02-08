"""Application settings and configuration.

This module defines all configuration values for the web service.
Settings are loaded from environment variables with fallback defaults
suitable for development. In production, all sensitive values should
be provided via environment variables or a secrets manager.

Configuration Hierarchy
-----------------------
Settings are resolved in the following order (highest priority first):

1. Environment variables (prefixed with APP_)
2. Configuration file (config.yaml)
3. Default values defined in this module

Environment Variable Naming
----------------------------
Environment variables follow the convention APP_{SECTION}_{KEY},
where section and key are uppercase with underscores:

- APP_DATABASE_HOST -> database.host
- APP_AUTH_TOKEN_TTL -> auth.token_ttl
- APP_CACHE_REDIS_URL -> cache.redis_url

Settings Sections
-----------------
- **General**: Application name, version, environment, debug mode
- **Database**: Connection string, pool size, timeouts
- **Auth**: Token configuration, session settings, password policy
- **Cache**: Redis configuration, TTLs, eviction policies
- **Email**: SMTP settings, sender addresses
- **Storage**: File upload limits, storage backend
- **Monitoring**: Metrics, logging, tracing configuration
- **Feature Flags**: Toggleable features for gradual rollout

Change History
--------------
- v1.0: Initial configuration with database and auth settings
- v1.1: Added Redis caching configuration
- v1.2: Added email and notification settings
- v1.3: Added feature flags system
- v1.4: Added monitoring and metrics configuration
- v1.5: Added storage backend configuration
"""

from __future__ import annotations

import os
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════
# GENERAL SETTINGS
# ═══════════════════════════════════════════════════════════════════════════

APP_NAME = "WebService"
APP_VERSION = "1.5.0"
ENVIRONMENT = os.getenv("APP_ENVIRONMENT", "development")
DEBUG = os.getenv("APP_DEBUG", "true").lower() == "true"
SECRET_KEY = os.getenv("APP_SECRET_KEY", "dev-secret-key-change-in-production")
BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")

# ═══════════════════════════════════════════════════════════════════════════
# DATABASE SETTINGS
# ═══════════════════════════════════════════════════════════════════════════

DATABASE_URL = os.getenv(
    "APP_DATABASE_URL",
    "postgresql://app:password@localhost:5432/webservice",
)
DATABASE_POOL_SIZE = int(os.getenv("APP_DATABASE_POOL_SIZE", "10"))
DATABASE_MAX_OVERFLOW = int(os.getenv("APP_DATABASE_MAX_OVERFLOW", "20"))
DATABASE_POOL_TIMEOUT = int(os.getenv("APP_DATABASE_POOL_TIMEOUT", "30"))
DATABASE_ECHO = os.getenv("APP_DATABASE_ECHO", "false").lower() == "true"

# ═══════════════════════════════════════════════════════════════════════════
# AUTHENTICATION SETTINGS
# ═══════════════════════════════════════════════════════════════════════════

# Token verification method -- this is the canonical method name used
# throughout the application for verifying authentication tokens.
# The User model must implement this method.
TOKEN_VERIFY_METHOD = "verify_token"

# Token time-to-live in seconds (24 hours default)
TOKEN_TTL_SECONDS = int(os.getenv("APP_AUTH_TOKEN_TTL", "86400"))

# Maximum concurrent sessions per user
MAX_SESSIONS_PER_USER = int(os.getenv("APP_AUTH_MAX_SESSIONS", "5"))

# Failed login attempt limits
MAX_LOGIN_ATTEMPTS = int(os.getenv("APP_AUTH_MAX_ATTEMPTS", "5"))
LOGIN_LOCKOUT_MINUTES = int(os.getenv("APP_AUTH_LOCKOUT_MINUTES", "15"))

# Password policy
PASSWORD_MIN_LENGTH = int(os.getenv("APP_AUTH_PASSWORD_MIN_LENGTH", "8"))
PASSWORD_REQUIRE_UPPERCASE = True
PASSWORD_REQUIRE_LOWERCASE = True
PASSWORD_REQUIRE_DIGIT = True
PASSWORD_REQUIRE_SPECIAL = True
PASSWORD_HISTORY_COUNT = int(os.getenv("APP_AUTH_PASSWORD_HISTORY", "5"))

# Two-factor authentication
TWO_FACTOR_ISSUER = os.getenv("APP_AUTH_2FA_ISSUER", APP_NAME)
TWO_FACTOR_DIGITS = 6
TWO_FACTOR_INTERVAL = 30

# ═══════════════════════════════════════════════════════════════════════════
# CACHE SETTINGS
# ═══════════════════════════════════════════════════════════════════════════

CACHE_BACKEND = os.getenv("APP_CACHE_BACKEND", "redis")
REDIS_URL = os.getenv("APP_CACHE_REDIS_URL", "redis://localhost:6379/0")
CACHE_DEFAULT_TTL = int(os.getenv("APP_CACHE_DEFAULT_TTL", "300"))
CACHE_MAX_ENTRIES = int(os.getenv("APP_CACHE_MAX_ENTRIES", "10000"))

# Per-type cache TTLs (in seconds)
CACHE_TTL_USER = 600
CACHE_TTL_ORDER = 300
CACHE_TTL_PRODUCT = 3600
CACHE_TTL_CONFIG = 86400

# ═══════════════════════════════════════════════════════════════════════════
# EMAIL SETTINGS
# ═══════════════════════════════════════════════════════════════════════════

SMTP_HOST = os.getenv("APP_SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("APP_SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("APP_SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("APP_SMTP_PASSWORD", "")
SMTP_USE_TLS = os.getenv("APP_SMTP_USE_TLS", "true").lower() == "true"
EMAIL_FROM_ADDRESS = os.getenv("APP_EMAIL_FROM", "noreply@webservice.example.com")
EMAIL_FROM_NAME = os.getenv("APP_EMAIL_FROM_NAME", APP_NAME)

# ═══════════════════════════════════════════════════════════════════════════
# STORAGE SETTINGS
# ═══════════════════════════════════════════════════════════════════════════

STORAGE_BACKEND = os.getenv("APP_STORAGE_BACKEND", "local")
STORAGE_LOCAL_PATH = os.getenv("APP_STORAGE_LOCAL_PATH", "/tmp/webservice/uploads")
STORAGE_S3_BUCKET = os.getenv("APP_STORAGE_S3_BUCKET", "")
STORAGE_S3_REGION = os.getenv("APP_STORAGE_S3_REGION", "us-east-1")
UPLOAD_MAX_SIZE_MB = int(os.getenv("APP_UPLOAD_MAX_SIZE_MB", "50"))
ALLOWED_UPLOAD_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".pdf",
    ".doc", ".docx", ".xls", ".xlsx", ".csv",
}

# ═══════════════════════════════════════════════════════════════════════════
# MONITORING SETTINGS
# ═══════════════════════════════════════════════════════════════════════════

LOG_LEVEL = os.getenv("APP_LOG_LEVEL", "INFO")
LOG_FORMAT = os.getenv("APP_LOG_FORMAT", "json")
LOG_FILE = os.getenv("APP_LOG_FILE", "")

METRICS_ENABLED = os.getenv("APP_METRICS_ENABLED", "true").lower() == "true"
METRICS_PORT = int(os.getenv("APP_METRICS_PORT", "9090"))
METRICS_PATH = "/metrics"

TRACING_ENABLED = os.getenv("APP_TRACING_ENABLED", "false").lower() == "true"
TRACING_ENDPOINT = os.getenv("APP_TRACING_ENDPOINT", "http://localhost:4317")
TRACING_SAMPLE_RATE = float(os.getenv("APP_TRACING_SAMPLE_RATE", "0.1"))

# ═══════════════════════════════════════════════════════════════════════════
# CORS SETTINGS
# ═══════════════════════════════════════════════════════════════════════════

CORS_ALLOWED_ORIGINS = os.getenv(
    "APP_CORS_ORIGINS",
    "http://localhost:3000,http://localhost:8080",
).split(",")
CORS_ALLOW_CREDENTIALS = True
CORS_MAX_AGE = 86400

# ═══════════════════════════════════════════════════════════════════════════
# RATE LIMITING SETTINGS
# ═══════════════════════════════════════════════════════════════════════════

RATE_LIMIT_ENABLED = os.getenv("APP_RATE_LIMIT_ENABLED", "true").lower() == "true"
RATE_LIMIT_DEFAULT_REQUESTS = int(os.getenv("APP_RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_DEFAULT_WINDOW = int(os.getenv("APP_RATE_LIMIT_WINDOW", "60"))
RATE_LIMIT_AUTH_REQUESTS = 10
RATE_LIMIT_AUTH_WINDOW = 60

# ═══════════════════════════════════════════════════════════════════════════
# FEATURE FLAGS
# ═══════════════════════════════════════════════════════════════════════════

FEATURE_FLAGS: dict[str, bool] = {
    "enable_2fa": True,
    "enable_oauth": False,
    "enable_webhooks": False,
    "enable_bulk_operations": True,
    "enable_csv_export": True,
    "enable_dark_mode": False,
    "enable_beta_features": ENVIRONMENT == "development",
}


def get_all_settings() -> dict[str, Any]:
    """Return all settings as a dictionary.

    Excludes sensitive values (passwords, secret keys) from the output.
    """
    sensitive_keys = {"SECRET_KEY", "SMTP_PASSWORD", "DATABASE_URL"}
    settings: dict[str, Any] = {}
    for key, value in globals().items():
        if key.startswith("_") or key.isupper() is False:
            continue
        if key in sensitive_keys:
            settings[key] = "***REDACTED***"
        else:
            settings[key] = value
    return settings
