package dev.featurestandards.generated.core;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.featurestandards.auth.AuthConfig;
import dev.featurestandards.auth.AuthFilter;
import dev.featurestandards.auth.AuthService;
import dev.featurestandards.core.authorization.AuthorizationPolicy;
import dev.featurestandards.core.authorization.Principal;
import dev.featurestandards.core.listing.Listing;
import jakarta.servlet.Filter;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.time.Clock;
import java.util.List;
import java.util.Map;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.core.Ordered;
import org.springframework.core.env.Environment;

@SpringBootApplication
public class CoreApplication {
    public static void main(String[] args) {
        if (args.length == 1 && args[0].equals("--sdk-origins")) {
            try {
                System.out.println(new ObjectMapper().writeValueAsString(Map.of(
                    "auth", AuthService.class.getProtectionDomain().getCodeSource().getLocation().toExternalForm(),
                    "authorization", AuthorizationPolicy.class.getProtectionDomain().getCodeSource().getLocation().toExternalForm(),
                    "listing", Listing.class.getProtectionDomain().getCodeSource().getLocation().toExternalForm()
                )));
            } catch (Exception failure) {
                System.err.println("Could not inspect SDK origins.");
                System.exit(1);
            }
            return;
        }
        SpringApplication.run(CoreApplication.class, args);
    }

    @Bean AuthConfig authConfig(Environment env) {
        var config = AuthConfig.load(env::getProperty);
        if (!config.store().equals("memory") || config.accountLifecycle())
            throw new IllegalArgumentException("This starter supports browser-session-v1 memory sessions only");
        if (config.demo() && !List.of("127.0.0.1", "localhost", "::1").contains(config.host()))
            throw new IllegalArgumentException("Demo mode requires a loopback AUTH_HOST");
        return config;
    }
    @Bean AuthService authService(AuthConfig config, Environment env) {
        return AuthService.create(config, AuthConfig.password(env::getProperty, config.demo()), Clock.systemUTC());
    }
    @Bean FilterRegistrationBean<AuthFilter> authFilter(AuthConfig config, AuthService service) {
        var filter = new FilterRegistrationBean<>(new AuthFilter(config, service));
        filter.addUrlPatterns("/auth/*", "/healthz");
        filter.setOrder(Ordered.HIGHEST_PRECEDENCE);
        return filter;
    }
    @Bean FilterRegistrationBean<Filter> productHeaders() {
        Filter headers = (input, output, chain) -> {
            var request = (HttpServletRequest) input;
            var response = (HttpServletResponse) output;
            response.setHeader("Cache-Control", "no-store");
            response.setHeader("X-Content-Type-Options", "nosniff");
            if (!request.getMethod().equals("GET")) {
                response.setHeader("Allow", "GET");
                response.setStatus(405);
                response.setContentType("application/json");
                response.getWriter().write("{\"error\":{\"code\":\"METHOD_NOT_ALLOWED\",\"message\":\"Request could not be completed.\"}}");
                return;
            }
            chain.doFilter(input, output);
        };
        var filter = new FilterRegistrationBean<>(headers);
        filter.addUrlPatterns("/api/*");
        filter.setOrder(Ordered.HIGHEST_PRECEDENCE + 1);
        return filter;
    }
    // Replace this bean with a trusted current-membership service when adapting the app.
    // A configured non-demo authentication user does not acquire demo roles.
    @Bean MembershipProvider membershipProvider(AuthConfig config) {
        return user -> config.demo() && user.id().equals("demo-user")
            ? new Principal(user.id(), "tenant-a", List.of("viewer")) : null;
    }
    @Bean DocumentProvider documentProvider(AuthConfig config) {
        return config.demo() ? CoreApplication::demoDocuments : List::of;
    }
    static List<Map<String, Object>> demoDocuments() {
        return List.of(
            Map.of("id", "own-b", "name", "Beta", "score", 2, "active", false, "tenantId", "tenant-a", "ownerId", "demo-user"),
            Map.of("id", "other-owner", "name", "Private", "score", 10, "active", true, "tenantId", "tenant-a", "ownerId", "other-user"),
            Map.of("id", "other-tenant", "name", "Secret", "score", 99, "active", true, "tenantId", "tenant-b", "ownerId", "demo-user"),
            Map.of("id", "own-a", "name", "Alpha", "score", 2, "active", true, "tenantId", "tenant-a", "ownerId", "demo-user")
        );
    }
}
