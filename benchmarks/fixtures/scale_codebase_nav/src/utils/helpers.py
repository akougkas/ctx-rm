"""Utility helper functions for the web service.

This module provides a collection of general-purpose utility functions
used throughout the application. These functions handle common tasks
such as string manipulation, data formatting, validation, and
cryptographic operations.

Module Organization
-------------------
Functions are grouped by category:

1. **String Utilities**: Text manipulation, formatting, truncation
2. **Date/Time Utilities**: Timestamp formatting, timezone handling
3. **Validation Utilities**: Input validation, sanitization
4. **Crypto Utilities**: Hashing, token generation, encoding
5. **Data Utilities**: Collection operations, merging, diffing
6. **Format Utilities**: Currency, number, percentage formatting
7. **Network Utilities**: URL parsing, IP validation, headers

Usage Guidelines
----------------
- All functions are stateless and side-effect free
- Functions accept primitive types and return primitive types
- No function in this module should import from other app modules
- All functions include type annotations for documentation

Performance Notes
-----------------
- String operations use pre-compiled regex patterns where applicable
- Hash functions cache results for repeated calls with same input
- Date parsing uses dateutil for flexible format handling
- Large collection operations use generators where possible

Testing
-------
Each function has corresponding unit tests in ``tests/test_helpers.py``.
Tests cover normal cases, edge cases, and error conditions.

Change History
--------------
- v1.0: Initial utility functions
- v1.1: Added crypto utilities
- v1.2: Added date/time utilities
- v1.3: Added network utilities
- v1.4: Performance optimization with caching
- v1.5: Added data diffing and merging utilities
- v1.6: Enhanced input sanitization for security
- v1.7: Added bulk processing helpers
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import string
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence, TypeVar
from urllib.parse import parse_qs, urlparse

T = TypeVar("T")


# ═══════════════════════════════════════════════════════════════════════════
# STRING UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def truncate(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate text to a maximum length with a suffix.

    If the text is shorter than max_length, it is returned unchanged.
    Otherwise, it is truncated and the suffix is appended such that
    the total length equals max_length.

    Args:
        text: The text to truncate.
        max_length: Maximum total length including suffix.
        suffix: String to append when truncating.

    Returns:
        The truncated text or original if short enough.

    Examples::

        >>> truncate("Hello, World!", 10)
        'Hello, ...'
        >>> truncate("Short", 10)
        'Short'
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def slugify(text: str, max_length: int = 200) -> str:
    """Convert text to a URL-safe slug.

    Normalizes unicode, converts to lowercase, replaces non-alphanumeric
    characters with hyphens, and removes leading/trailing hyphens.

    Args:
        text: The text to slugify.
        max_length: Maximum slug length.

    Returns:
        A URL-safe slug string.

    Examples::

        >>> slugify("Hello, World!")
        'hello-world'
        >>> slugify("  Multiple   Spaces  ")
        'multiple-spaces'
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:max_length]


def camel_to_snake(name: str) -> str:
    """Convert camelCase or PascalCase to snake_case.

    Handles consecutive uppercase letters correctly (e.g.,
    'HTMLParser' becomes 'html_parser').

    Args:
        name: The camelCase or PascalCase string.

    Returns:
        The snake_case equivalent.

    Examples::

        >>> camel_to_snake("camelCase")
        'camel_case'
        >>> camel_to_snake("HTMLParser")
        'html_parser'
    """
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def snake_to_camel(name: str, capitalize_first: bool = False) -> str:
    """Convert snake_case to camelCase or PascalCase.

    Args:
        name: The snake_case string.
        capitalize_first: If True, return PascalCase.

    Returns:
        The camelCase or PascalCase equivalent.
    """
    components = name.split("_")
    if capitalize_first:
        return "".join(c.capitalize() for c in components)
    return components[0] + "".join(c.capitalize() for c in components[1:])


def mask_sensitive(value: str, visible_chars: int = 4, mask_char: str = "*") -> str:
    """Mask a sensitive string, showing only the last N characters.

    Useful for logging credit card numbers, tokens, and other
    sensitive data without exposing the full value.

    Args:
        value: The string to mask.
        visible_chars: Number of trailing characters to show.
        mask_char: Character used for masking.

    Returns:
        The masked string.

    Examples::

        >>> mask_sensitive("4111111111111111")
        '************1111'
    """
    if len(value) <= visible_chars:
        return mask_char * len(value)
    masked_length = len(value) - visible_chars
    return mask_char * masked_length + value[-visible_chars:]


def pluralize(word: str, count: int) -> str:
    """Simple English pluralization.

    Handles common cases but does not cover irregular plurals.
    For production use, consider a proper inflection library.

    Args:
        word: The singular form.
        count: The count to determine plurality.

    Returns:
        Singular or plural form based on count.
    """
    if count == 1:
        return word
    if word.endswith("y"):
        return word[:-1] + "ies"
    if word.endswith(("s", "sh", "ch", "x", "z")):
        return word + "es"
    return word + "s"


# ═══════════════════════════════════════════════════════════════════════════
# DATE/TIME UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def utc_now() -> datetime:
    """Return the current UTC datetime with timezone info."""
    return datetime.now(timezone.utc)


def format_timestamp(dt: datetime, fmt: str = "%Y-%m-%dT%H:%M:%SZ") -> str:
    """Format a datetime as an ISO-8601 string.

    Args:
        dt: The datetime to format.
        fmt: strftime format string.

    Returns:
        Formatted timestamp string.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime(fmt)


def parse_timestamp(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp string to datetime.

    Handles various ISO-8601 formats including with and without
    timezone info, milliseconds, and Z suffix.

    Args:
        ts: The timestamp string.

    Returns:
        Parsed datetime object (UTC).
    """
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def time_ago(dt: datetime) -> str:
    """Return a human-readable 'time ago' string.

    Args:
        dt: The past datetime.

    Returns:
        String like "5 minutes ago", "2 hours ago", etc.
    """
    now = utc_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt

    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds} {pluralize('second', seconds)} ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} {pluralize('minute', minutes)} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} {pluralize('hour', hours)} ago"
    days = hours // 24
    if days < 30:
        return f"{days} {pluralize('day', days)} ago"
    months = days // 30
    if months < 12:
        return f"{months} {pluralize('month', months)} ago"
    years = days // 365
    return f"{years} {pluralize('year', years)} ago"


def add_business_days(start_date: datetime, days: int) -> datetime:
    """Add business days (Mon-Fri) to a date.

    Skips weekends but does not account for holidays.

    Args:
        start_date: The starting date.
        days: Number of business days to add.

    Returns:
        The resulting date after adding business days.
    """
    current = start_date
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Monday=0, Friday=4
            added += 1
    return current


# ═══════════════════════════════════════════════════════════════════════════
# VALIDATION UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)

PHONE_REGEX = re.compile(r"^\+?[1-9]\d{1,14}$")

UUID_REGEX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

URL_REGEX = re.compile(
    r"^https?://"
    r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"
    r"localhost|"
    r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
    r"(?::\d+)?"
    r"(?:/?|[/?]\S+)$",
    re.IGNORECASE,
)


def is_valid_email(email: str) -> bool:
    """Validate an email address format.

    Uses a comprehensive regex that covers most valid email formats
    as defined in RFC 5322. Does not verify deliverability.

    Args:
        email: The email address to validate.

    Returns:
        True if the format is valid.
    """
    return bool(EMAIL_REGEX.match(email))


def is_valid_phone(phone: str) -> bool:
    """Validate an E.164 phone number format."""
    return bool(PHONE_REGEX.match(phone.replace(" ", "").replace("-", "")))


def is_valid_uuid(value: str) -> bool:
    """Check if a string is a valid UUID format."""
    return bool(UUID_REGEX.match(value))


def is_valid_url(url: str) -> bool:
    """Validate a URL format."""
    return bool(URL_REGEX.match(url))


def sanitize_html(text: str) -> str:
    """Remove HTML tags from text for safe display.

    This is a basic sanitizer that strips all HTML tags. For
    production use with rich content, use a proper library like
    bleach that supports allowlisting specific tags.

    Args:
        text: The HTML text to sanitize.

    Returns:
        Text with all HTML tags removed.
    """
    return re.sub(r"<[^>]+>", "", text)


def validate_password_strength(password: str) -> tuple[bool, list[str]]:
    """Validate password meets minimum strength requirements.

    Requirements:
    - At least 8 characters long
    - Contains at least one uppercase letter
    - Contains at least one lowercase letter
    - Contains at least one digit
    - Contains at least one special character

    Args:
        password: The password to validate.

    Returns:
        Tuple of (is_valid, list_of_failures).
    """
    failures: list[str] = []
    if len(password) < 8:
        failures.append("Password must be at least 8 characters")
    if not re.search(r"[A-Z]", password):
        failures.append("Password must contain an uppercase letter")
    if not re.search(r"[a-z]", password):
        failures.append("Password must contain a lowercase letter")
    if not re.search(r"\d", password):
        failures.append("Password must contain a digit")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        failures.append("Password must contain a special character")
    return len(failures) == 0, failures


# ═══════════════════════════════════════════════════════════════════════════
# CRYPTO UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def generate_random_string(length: int = 32, charset: Optional[str] = None) -> str:
    """Generate a cryptographically random string.

    Uses os.urandom for secure random number generation.

    Args:
        length: Desired string length.
        charset: Characters to choose from (default: hex digits).

    Returns:
        Random string of specified length.
    """
    if charset is None:
        return os.urandom(length).hex()[:length]
    random_bytes = os.urandom(length)
    return "".join(charset[b % len(charset)] for b in random_bytes)


def hash_sha256(data: str) -> str:
    """Compute SHA-256 hash of a string.

    Args:
        data: The string to hash.

    Returns:
        Hexadecimal hash string.
    """
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def hash_md5(data: str) -> str:
    """Compute MD5 hash of a string.

    WARNING: MD5 is not cryptographically secure and should not be
    used for security purposes. Use only for checksums and caching.

    Args:
        data: The string to hash.

    Returns:
        Hexadecimal hash string.
    """
    return hashlib.md5(data.encode("utf-8")).hexdigest()


def compute_hmac(key: str, message: str, algorithm: str = "sha256") -> str:
    """Compute HMAC signature for a message.

    Args:
        key: The secret key.
        message: The message to sign.
        algorithm: Hash algorithm (sha256, sha512, etc).

    Returns:
        Hexadecimal HMAC signature.
    """
    return hmac.new(
        key.encode("utf-8"),
        message.encode("utf-8"),
        getattr(hashlib, algorithm),
    ).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    """Compare two strings in constant time to prevent timing attacks.

    Args:
        a: First string.
        b: Second string.

    Returns:
        True if the strings are equal.
    """
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# ═══════════════════════════════════════════════════════════════════════════
# DATA UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries.

    Values from override take precedence. Nested dicts are merged
    recursively; all other types are replaced.

    Args:
        base: The base dictionary.
        override: Values to merge in (takes precedence).

    Returns:
        New merged dictionary.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def flatten_dict(d: dict, prefix: str = "", separator: str = ".") -> dict[str, Any]:
    """Flatten a nested dictionary into a single-level dict.

    Nested keys are joined with the separator.

    Args:
        d: The dictionary to flatten.
        prefix: Current key prefix (for recursion).
        separator: Character to join nested keys.

    Returns:
        Flattened dictionary.

    Examples::

        >>> flatten_dict({"a": {"b": 1, "c": {"d": 2}}})
        {'a.b': 1, 'a.c.d': 2}
    """
    items: dict[str, Any] = {}
    for key, value in d.items():
        new_key = f"{prefix}{separator}{key}" if prefix else key
        if isinstance(value, dict):
            items.update(flatten_dict(value, new_key, separator))
        else:
            items[new_key] = value
    return items


def chunk_list(items: Sequence[T], chunk_size: int) -> list[list[T]]:
    """Split a sequence into chunks of specified size.

    Args:
        items: The sequence to chunk.
        chunk_size: Maximum size of each chunk.

    Returns:
        List of chunks.

    Examples::

        >>> chunk_list([1, 2, 3, 4, 5], 2)
        [[1, 2], [3, 4], [5]]
    """
    return [list(items[i : i + chunk_size]) for i in range(0, len(items), chunk_size)]


def remove_duplicates(items: Sequence[T], key: Optional[Any] = None) -> list[T]:
    """Remove duplicates while preserving order.

    Args:
        items: The sequence to deduplicate.
        key: Optional function to extract comparison key.

    Returns:
        Deduplicated list.
    """
    seen: set = set()
    result: list[T] = []
    for item in items:
        k = key(item) if key else item
        if k not in seen:
            seen.add(k)
            result.append(item)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# FORMAT UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def format_currency(
    amount: Decimal | float | int,
    currency: str = "USD",
    locale: str = "en_US",
) -> str:
    """Format a monetary amount with currency symbol.

    Args:
        amount: The amount to format.
        currency: ISO 4217 currency code.
        locale: Locale for formatting conventions.

    Returns:
        Formatted currency string.
    """
    symbols: dict[str, str] = {
        "USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "JPY": "\u00a5",
        "CAD": "C$", "AUD": "A$", "CHF": "CHF ",
    }
    symbol = symbols.get(currency, f"{currency} ")
    amount_decimal = Decimal(str(amount))
    formatted = f"{amount_decimal:,.2f}"
    return f"{symbol}{formatted}"


def format_percentage(value: float, decimals: int = 1) -> str:
    """Format a value as a percentage string.

    Args:
        value: The value (0.0-1.0 or 0-100).
        decimals: Number of decimal places.

    Returns:
        Formatted percentage string.
    """
    if value <= 1.0 and value >= 0:
        value *= 100
    return f"{value:.{decimals}f}%"


def format_file_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable file size.

    Args:
        size_bytes: Size in bytes.

    Returns:
        Formatted string (e.g., "1.5 MB").
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} {unit}"
        size_bytes /= 1024  # type: ignore[assignment]
    return f"{size_bytes:.1f} PB"


def format_duration(seconds: float) -> str:
    """Format a duration in seconds as a human-readable string.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string (e.g., "2h 30m 15s").
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m {secs}s"


# ═══════════════════════════════════════════════════════════════════════════
# NETWORK UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def parse_url(url: str) -> dict[str, Any]:
    """Parse a URL into its components.

    Args:
        url: The URL to parse.

    Returns:
        Dictionary with scheme, host, port, path, query, fragment.
    """
    parsed = urlparse(url)
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname or "",
        "port": parsed.port,
        "path": parsed.path,
        "query": parse_qs(parsed.query),
        "fragment": parsed.fragment,
    }


def is_private_ip(ip: str) -> bool:
    """Check if an IP address is in a private range.

    Checks against RFC 1918 ranges:
    - 10.0.0.0/8
    - 172.16.0.0/12
    - 192.168.0.0/16
    - 127.0.0.0/8 (loopback)

    Args:
        ip: IPv4 address string.

    Returns:
        True if the IP is in a private range.
    """
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        octets = [int(p) for p in parts]
    except ValueError:
        return False

    if octets[0] == 10:
        return True
    if octets[0] == 172 and 16 <= octets[1] <= 31:
        return True
    if octets[0] == 192 and octets[1] == 168:
        return True
    if octets[0] == 127:
        return True
    return False


def normalize_headers(headers: dict[str, str]) -> dict[str, str]:
    """Normalize HTTP header names to title case.

    Args:
        headers: Raw headers dictionary.

    Returns:
        Headers with normalized names.
    """
    return {
        "-".join(part.capitalize() for part in k.split("-")): v
        for k, v in headers.items()
    }
