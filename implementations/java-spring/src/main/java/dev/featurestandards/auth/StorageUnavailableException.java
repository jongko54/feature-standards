package dev.featurestandards.auth;

/** Deliberately has no SQL cause: connection errors can contain credentials or URLs. */
public final class StorageUnavailableException extends RuntimeException {
    public StorageUnavailableException() { super("Authentication storage is unavailable"); }
}
