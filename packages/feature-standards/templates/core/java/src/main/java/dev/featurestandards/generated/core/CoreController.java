package dev.featurestandards.generated.core;

import dev.featurestandards.auth.AuthService;
import dev.featurestandards.auth.StorageUnavailableException;
import dev.featurestandards.core.authorization.AuthorizationPolicy;
import dev.featurestandards.core.authorization.Grant;
import dev.featurestandards.core.authorization.Principal;
import dev.featurestandards.core.authorization.Resource;
import dev.featurestandards.core.listing.Listing;
import jakarta.servlet.http.HttpServletRequest;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

/** Product glue only; authentication, policy and list semantics come from library JARs. */
@RestController
public final class CoreController {
    private static final AuthorizationPolicy POLICY = new AuthorizationPolicy(List.of(
        new Grant("viewer", "documents:list", "tenant"), new Grant("viewer", "documents:read", "owner")
    ));
    private static final Listing.Schema SCHEMA = new Listing.Schema(
        Map.of("id", "string", "name", "string", "score", "integer", "active", "boolean"),
        Map.of("name", "string", "score", "integer", "active", "boolean")
    );
    private final AuthService auth;
    private final MembershipProvider membership;
    private final DocumentProvider documents;

    public CoreController(AuthService auth, MembershipProvider membership, DocumentProvider documents) {
        this.auth = auth; this.membership = membership; this.documents = documents;
    }

    @GetMapping("/api/profile")
    ResponseEntity<?> profile(@CookieValue(name = "fs_session", required = false) String token) {
        var session = auth.session(token);
        if (session == null) throw new ProductFailure(401, "UNAUTHENTICATED");
        return response(200, Map.of("user", session.user()));
    }

    private Principal principal(String token) {
        var session = auth.session(token);
        if (session == null) throw new ProductFailure(401, "UNAUTHENTICATED");
        Principal principal;
        try { principal = membership.resolve(session.user()); }
        catch (Exception failure) { throw new ProductFailure(503, "AUTHORIZATION_UNAVAILABLE"); }
        if (principal == null || !session.user().id().equals(principal.subjectId()))
            throw new ProductFailure(403, "FORBIDDEN");
        return principal;
    }

    private List<Map<String, Object>> currentDocuments() {
        try {
            var current = documents.load();
            if (current == null) throw new ProductFailure(500, "INVALID_LIST_DATA");
            return current;
        } catch (ProductFailure failure) { throw failure; }
        catch (Exception failure) { throw new ProductFailure(500, "INVALID_LIST_DATA"); }
    }

    private static Resource resource(Map<String, Object> row) {
        if (row == null || !(row.get("tenantId") instanceof String tenant) || !(row.get("ownerId") instanceof String owner))
            throw new ProductFailure(500, "INVALID_LIST_DATA");
        return new Resource(tenant, owner);
    }

    private static Map<String, Object> publicDocument(Map<String, Object> row) {
        Map<String, Object> result = new HashMap<>();
        for (var field : List.of("id", "name", "score", "active")) {
            if (!row.containsKey(field) || row.get(field) == null) throw new ProductFailure(500, "INVALID_LIST_DATA");
            result.put(field, row.get(field));
        }
        return result;
    }

    @GetMapping("/api/documents")
    ResponseEntity<?> list(HttpServletRequest request, @CookieValue(name = "fs_session", required = false) String token) {
        var principal = principal(token);
        if (!POLICY.decide(principal, "documents:list", new Resource(principal.tenantId(), null)).allowed())
            throw new ProductFailure(403, "FORBIDDEN");
        var visible = new ArrayList<Map<String, Object>>();
        for (var row : currentDocuments()) {
            // No count, filter or pagination is evaluated on inaccessible records.
            if (POLICY.decide(principal, "documents:read", resource(row)).allowed()) visible.add(publicDocument(row));
        }
        String raw = request.getQueryString();
        var query = Listing.parseQuery(raw == null ? "" : raw, SCHEMA);
        return response(200, Listing.page(visible, query, SCHEMA));
    }

    @GetMapping("/api/documents/{documentId}")
    ResponseEntity<?> document(@PathVariable("documentId") String id,
            @CookieValue(name = "fs_session", required = false) String token) {
        var principal = principal(token);
        for (var row : currentDocuments()) {
            if (row == null) throw new ProductFailure(500, "INVALID_LIST_DATA");
            if (!id.equals(row.get("id"))) continue;
            if (!POLICY.decide(principal, "documents:read", resource(row)).allowed()) throw new ProductFailure(403, "FORBIDDEN");
            return response(200, publicDocument(row));
        }
        throw new ProductFailure(403, "FORBIDDEN");
    }

    @ExceptionHandler(ProductFailure.class)
    ResponseEntity<?> productFailure(ProductFailure failure) { return error(failure.status, failure.code); }

    @ExceptionHandler(Listing.Error.class)
    ResponseEntity<?> listingFailure(Listing.Error failure) {
        return error(failure.code().equals("INVALID_LIST_QUERY") ? 400 : 500, failure.code());
    }

    @ExceptionHandler(StorageUnavailableException.class)
    ResponseEntity<?> authUnavailable() { return error(503, "STORAGE_UNAVAILABLE"); }

    private static ResponseEntity<?> error(int status, String code) {
        return response(status, Map.of("error", Map.of("code", code, "message", "Request could not be completed.")));
    }
    private static ResponseEntity<?> response(int status, Object body) {
        // The /api filter owns the canonical headers, including error responses.
        return ResponseEntity.status(status).body(body);
    }
    private static final class ProductFailure extends RuntimeException {
        final int status; final String code;
        ProductFailure(int status, String code) { super(code); this.status = status; this.code = code; }
    }
}
