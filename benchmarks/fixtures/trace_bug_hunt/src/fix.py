from src.auth import extract_user_id


def safe_extract(payload: dict) -> str | None:
    """TODO: harden this wrapper against missing user_id."""
    return extract_user_id(payload)

