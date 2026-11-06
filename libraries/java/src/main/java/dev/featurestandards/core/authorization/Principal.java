package dev.featurestandards.core.authorization;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
/** Current server-owned membership. Invalid values are denied by the policy. */
public record Principal(String subjectId, String tenantId, List<String> roles) {
    public Principal { if (roles != null) roles = Collections.unmodifiableList(new ArrayList<>(roles)); }
}
