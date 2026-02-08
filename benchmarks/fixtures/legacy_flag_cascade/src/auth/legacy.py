"""Legacy authentication module.

Handles authentication flow for users on the legacy auth system.
The LEGACY_AUTH flag determines whether legacy paths are active.
"""

from config.flags import LEGACY_AUTH, SAFE_MODE


def authenticate_user(request):
    """Authenticate a user via legacy or modern flow.

    The legacy branch is active when LEGACY_AUTH is enabled.
    """
    user = extract_user(request)

    # Bug: should be `if LEGACY_AUTH:` instead of `if not LEGACY_AUTH:`
    if not LEGACY_AUTH:
        token = issue_legacy_token(user)
        if SAFE_MODE:
            token = sanitize_token(token)
        return {"auth": "legacy", "token": token}

    return modern_auth_flow(user)


def extract_user(request):
    """Pull user identity from the request headers."""
    return request.get("X-User-Id", "anonymous")


def issue_legacy_token(user):
    """Generate a legacy-format auth token."""
    return f"legacy-{user}-token"


def sanitize_token(token):
    """Strip unsafe characters from a token when SAFE_MODE is on."""
    return token.replace("<", "").replace(">", "")


def modern_auth_flow(user):
    """Delegate to the modern OAuth2 auth flow."""
    return {"auth": "modern", "user": user}
