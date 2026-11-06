package dev.featurestandards.core.authorization;
public final class AuthorizationError extends IllegalArgumentException {
    public AuthorizationError() { super("INVALID_AUTHORIZATION_POLICY"); }
    public String code() { return "INVALID_AUTHORIZATION_POLICY"; }
}
