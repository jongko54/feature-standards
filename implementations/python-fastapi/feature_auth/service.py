"""Composition root for the interchangeable store adapters."""

from collections.abc import Callable

from .core import AuthService, AuthStore, Settings


def build_service(settings: Settings, store: AuthStore | None, clock: Callable[[], float]):
    if settings.store not in ("memory", "postgres"):
        raise ValueError("AUTH_STORE must be memory or postgres")
    if settings.account_lifecycle and settings.store != "postgres":
        raise ValueError("AUTH_ACCOUNT_LIFECYCLE requires postgres storage")
    if store is None:
        if settings.store == "postgres":
            from .postgres import PostgresStore

            store = PostgresStore(settings)
        else:
            from .memory import AuthState

            store = AuthState(settings, clock)
    return AuthService(settings, store)
