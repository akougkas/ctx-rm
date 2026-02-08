def extract_user_id(payload: dict) -> str:
    """Extract user id from auth payload.

    Bug: raises KeyError for partial payloads.
    """
    return payload["user_id"]

