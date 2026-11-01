"""Backward-compatible uvicorn entry point and v1 imports."""

from feature_auth import (  # noqa: F401
    AuthError,
    AuthState,
    Settings,
    create_app,
    current_user,
)
from feature_auth.core import normalize_email  # noqa: F401

app = create_app()
