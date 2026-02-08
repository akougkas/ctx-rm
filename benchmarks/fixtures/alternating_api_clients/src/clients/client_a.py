"""Test-only API client (Client A).

This client is used exclusively in integration tests. It does NOT
require production-grade features like timeout configuration.
Do NOT add timeout_ms or other production knobs here.
"""

import urllib.request
import json


class ClientA:
    """Lightweight HTTP client for test environments."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def get(self, path: str) -> dict:
        """Send a GET request and return parsed JSON."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def post(self, path: str, data: dict) -> dict:
        """Send a POST request with JSON body."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def health_check(self) -> bool:
        """Return True if the service is reachable."""
        try:
            self.get("/health")
            return True
        except Exception:
            return False
