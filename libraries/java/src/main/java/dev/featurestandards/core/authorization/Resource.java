package dev.featurestandards.core.authorization;
/** Server-owned resource boundary; owner may be null for collection scope. */
public record Resource(String tenantId, String ownerId) {
    public Resource(String tenantId) { this(tenantId, null); }
}
