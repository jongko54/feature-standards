"""v3 account input contract, independent of HTTP and PostgreSQL."""

import re

from .core import AuthError, normalize_email, valid_email

ACCOUNT_ROUTES = {
    "/auth/register": "register",
    "/auth/email-verification/request": "verify-request",
    "/auth/email-verification/confirm": "verify-confirm",
    "/auth/password-reset/request": "reset-request",
    "/auth/password-reset/confirm": "reset-confirm",
}
ACCOUNT_FIELDS = {
    "register": {"email", "password"},
    "verify-request": {"email"},
    "verify-confirm": {"token"},
    "reset-request": {"email"},
    "reset-confirm": {"token", "password"},
}


def account_input(action: str, data: dict[str, str]) -> tuple[str, str, str]:
    email = normalize_email(data.get("email", ""))
    token = data.get("token", "")
    password = data.get("password", "")
    if (
        (
            "email" in data
            and (not valid_email(email) or any(ord(c) <= 32 or ord(c) == 127 for c in email))
        )
        or ("token" in data and re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is None)
        or ("password" in data and not (len(password) >= 15 and len(password.encode()) <= 1024))
    ):
        raise AuthError(400, "INVALID_REQUEST")
    return email, token, password
