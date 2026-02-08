"""Feature flags for the application.

These flags control runtime behavior and should be modified with care.
SAFE_MODE in particular must remain True in production to ensure
token sanitization is applied.
"""

LEGACY_AUTH = True
SAFE_MODE = True
DEBUG_MODE = False
ENABLE_METRICS = True
RATE_LIMIT_ENABLED = True
MAX_RETRIES = 3
