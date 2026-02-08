"""Network retry logic.

Implements retry with backoff for transient network failures.

BUG: Uses retries=5 and linear backoff. The maintainer's guidance
is to use retries=3 with exponential_backoff instead.
"""

import time
import random


def retry_request(func, *args, retries=5, **kwargs):
    """Retry a network request with linear backoff.

    BUG: Should use retries=3 and exponential_backoff, not
    retries=5 with linear delay.
    """
    last_error = None
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_error = exc
            # BUG: linear backoff -- should be exponential_backoff
            delay = 1.0 * (attempt + 1)
            delay += random.uniform(0, 0.5)
            time.sleep(delay)
    raise last_error


def linear_backoff(attempt: int) -> float:
    """Compute linear backoff delay."""
    return 1.0 * (attempt + 1)


def make_request(url: str, method: str = "GET") -> dict:
    """Placeholder for an HTTP request."""
    import urllib.request
    import json

    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())
