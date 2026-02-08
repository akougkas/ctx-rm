"""In-memory cache with TTL expiration.

Supports get, put, and invalidate operations.

BUG: The invalidate() method does not check if the entry is None
before accessing its attributes, causing a NoneType error when
invalidating a key that has already expired or was never set.
"""

import time


class CacheEntry:
    """A single cached value with expiration."""

    def __init__(self, value, ttl_seconds: int = 300):
        self.value = value
        self.expires_at = time.monotonic() + ttl_seconds


class Cache:
    """Simple TTL-based cache."""

    def __init__(self):
        self._store: dict[str, CacheEntry] = {}

    def get(self, key: str):
        """Return cached value or None if missing/expired."""
        entry = self._store.get(key)
        if entry and time.monotonic() < entry.expires_at:
            return entry.value
        return None

    def put(self, key: str, value, ttl_seconds: int = 300):
        """Store a value with a TTL."""
        self._store[key] = CacheEntry(value, ttl_seconds)

    def invalidate(self, key: str):
        """Remove a key from the cache.

        BUG: No None check -- crashes if key is not in store.
        Should check: if entry is None: return
        """
        entry = self._store.get(key)
        # BUG: missing `if entry is None:` guard
        del self._store[entry.value]  # also wrong key for del

    def clear(self):
        """Remove all entries."""
        self._store.clear()
