package dev.featurestandards.core.authorization;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class AuthorizationPolicyTest {
    @Test void sharedVectors() throws Exception {
        JsonNode fixture = new ObjectMapper().readTree(Path.of("../../features/authorization/scenarios.json").toFile());
        for (JsonNode c : fixture.get("cases")) {
            List<Grant> grants = new ArrayList<>();
            for (JsonNode grant : c.get("grants")) grants.add(new Grant(grant.get("role").asText(),grant.get("permission").asText(),grant.get("scope").asText()));
            String id = c.get("id").asText();
            if (c.get("expected").has("error")) {
                AuthorizationError error = assertThrows(AuthorizationError.class, () -> new AuthorizationPolicy(grants), id);
                assertEquals(c.get("expected").get("error").asText(),error.code(),id);
                continue;
            }
            JsonNode p = c.get("principal");
            Principal principal = null;
            if (!p.isNull()) {
                List<String> roles = new ArrayList<>();
                for (JsonNode role : p.get("roles")) roles.add(role.asText());
                principal = new Principal(p.get("subjectId").asText(),p.get("tenantId").asText(),roles);
            }
            JsonNode r = c.get("resource");
            Resource resource = new Resource(r.get("tenantId").asText(),r.hasNonNull("ownerId") ? r.get("ownerId").asText() : null);
            Decision actual = new AuthorizationPolicy(grants).decide(principal,c.get("permission").asText(),resource);
            assertEquals(c.get("expected").get("allowed").asBoolean(),actual.allowed(),id);
            assertEquals(c.get("expected").get("code").asText(),actual.code(),id);
        }
    }
    @Test void snapshotsAndNullInputs() {
        List<Grant> grants = new ArrayList<>(List.of(new Grant("viewer","documents:read","tenant")));
        List<String> roles = new ArrayList<>(List.of("viewer"));
        Principal principal = new Principal("alice","tenant-a",roles);
        AuthorizationPolicy policy = new AuthorizationPolicy(grants);
        grants.clear(); roles.clear();
        assertTrue(policy.decide(principal,"documents:read",new Resource("tenant-a")).allowed());
        assertThrows(UnsupportedOperationException.class, () -> principal.roles().clear());
        assertEquals("FORBIDDEN",policy.decide(new Principal("alice","tenant-a",null),"documents:read",new Resource("tenant-a")).code());
        assertEquals("FORBIDDEN",policy.decide(new Principal("alice","tenant-a",Arrays.asList("viewer",null)),"documents:read",new Resource("tenant-a")).code());
        assertEquals("FORBIDDEN",policy.decide(principal,"documents:read",null).code());
        assertThrows(AuthorizationError.class, () -> new AuthorizationPolicy(null));
    }
}
