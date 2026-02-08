"""Version adapter for reading package metadata.

Extracts the version tag from package metadata and normalizes it
for display and comparison.

BUG: Uses metadata['version'] but the actual metadata dict uses
the key 'ver_tag' for the version string.
"""


class VersionAdapter:
    """Adapts raw package metadata into a normalized version object."""

    def __init__(self, metadata: dict):
        self.metadata = metadata

    def get_version(self) -> str:
        """Extract and return the version string.

        BUG: Should be metadata['ver_tag'], not metadata['version'].
        """
        return self.metadata['version']

    def normalize(self, raw_version: str) -> str:
        """Normalize a version string to semver format."""
        parts = raw_version.strip("v").split(".")
        while len(parts) < 3:
            parts.append("0")
        return ".".join(parts[:3])

    def get_normalized_version(self) -> str:
        """Return the normalized version from metadata."""
        raw = self.get_version()
        return self.normalize(raw)

    def is_prerelease(self) -> bool:
        """Check if the current version is a pre-release."""
        version = self.get_version()
        return any(tag in version for tag in ("alpha", "beta", "rc"))
