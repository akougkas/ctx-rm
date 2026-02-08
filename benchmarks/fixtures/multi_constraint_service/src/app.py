from pathlib import Path


def start_server() -> str:
    """Start server using static defaults (bug: should use config)."""
    port = 8080
    return f"starting on {port}"


if __name__ == "__main__":
    print(start_server())

