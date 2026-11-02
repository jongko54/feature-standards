package dev.featurestandards.examples;

import dev.featurestandards.auth.AuthService;
import dev.featurestandards.auth.StorageUnavailableException;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public final class ProfileController {
    private final AuthService service;
    public ProfileController(AuthService service) { this.service = service; }

    @GetMapping("/api/profile")
    ResponseEntity<?> profile(@CookieValue(name = "fs_session", required = false) String token) {
        var session = service.session(token);
        if (session == null) return error(401, "UNAUTHENTICATED");
        return response(200, Map.of("user", session.user()));
    }

    @ExceptionHandler(StorageUnavailableException.class)
    ResponseEntity<?> storageUnavailable() { return error(503, "STORAGE_UNAVAILABLE"); }

    private static ResponseEntity<?> error(int status, String code) {
        return response(status, Map.of("error", Map.of("code", code, "message", code)));
    }

    private static ResponseEntity<?> response(int status, Object body) {
        return ResponseEntity.status(status).header("Cache-Control", "no-store")
                .header("X-Content-Type-Options", "nosniff").body(body);
    }
}
