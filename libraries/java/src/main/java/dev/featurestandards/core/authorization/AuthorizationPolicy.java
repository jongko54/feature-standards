package dev.featurestandards.core.authorization;

import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

/** Immutable rbac-v1 policy. Identity must be provided by the server. */
public final class AuthorizationPolicy {
    private static final Pattern IDENTIFIER = Pattern.compile("[A-Za-z0-9][A-Za-z0-9._:-]{0,63}");
    private static final Pattern ROLE = Pattern.compile("[a-z][a-z0-9_-]{0,63}");
    private static final Pattern PERMISSION = Pattern.compile("[a-z][a-z0-9_.:-]{0,63}");
    private static final Decision DENY = new Decision(false, "FORBIDDEN");
    private final List<Grant> grants;

    private static boolean valid(String value, Pattern pattern) { return value != null && pattern.matcher(value).matches(); }
    public AuthorizationPolicy(List<Grant> grants) {
        if (grants == null || grants.size() > 256) throw new AuthorizationError();
        Set<List<String>> seen = new HashSet<>();
        for (Grant grant : grants) {
            if (grant == null || !valid(grant.role(), ROLE) || !valid(grant.permission(), PERMISSION)
                || !("tenant".equals(grant.scope()) || "owner".equals(grant.scope()))
                || !seen.add(List.of(grant.role(), grant.permission()))) throw new AuthorizationError();
        }
        this.grants = List.copyOf(grants);
    }
    public Decision decide(Principal principal, String permission, Resource resource) {
        if (principal == null) return new Decision(false, "UNAUTHENTICATED");
        if (!valid(principal.subjectId(), IDENTIFIER) || !valid(principal.tenantId(), IDENTIFIER)
            || principal.roles() == null || principal.roles().size() > 16 || !valid(permission, PERMISSION)
            || resource == null || !valid(resource.tenantId(), IDENTIFIER)
            || (resource.ownerId() != null && !valid(resource.ownerId(), IDENTIFIER))
            || !principal.tenantId().equals(resource.tenantId())) return DENY;
        Set<String> roles = new HashSet<>();
        for (String role : principal.roles()) if (!valid(role, ROLE) || !roles.add(role)) return DENY;
        for (Grant grant : grants) {
            if (roles.contains(grant.role()) && grant.permission().equals(permission)
                && (grant.scope().equals("tenant") || principal.subjectId().equals(resource.ownerId())))
                return new Decision(true, "ALLOWED");
        }
        return DENY;
    }
}
