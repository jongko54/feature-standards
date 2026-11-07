package dev.featurestandards.examples.core;

import dev.featurestandards.auth.AuthConfig;
import dev.featurestandards.auth.AuthFilter;
import dev.featurestandards.auth.AuthService;
import dev.featurestandards.core.authorization.Principal;
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
    public static void main(String[] args) { SpringApplication.run(CoreApplication.class, args); }

    @Bean AuthConfig authConfig(Environment env) {
        var config = AuthConfig.load(env::getProperty);
        if (!config.demo() || !config.store().equals("memory") || !config.host().equals("127.0.0.1"))
            throw new IllegalArgumentException("Core example requires explicit loopback memory demo configuration");
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
    @Bean MembershipProvider membershipProvider() {
        return user -> user.id().equals("demo-user") ? new Principal(user.id(), "tenant-a", List.of("viewer")) : null;
    }
    @Bean DocumentProvider documentProvider() { return CoreApplication::demoDocuments; }
    static List<Map<String, Object>> demoDocuments() {
        return List.of(
            Map.of("id", "own-b", "name", "Beta", "score", 2, "active", false, "tenantId", "tenant-a", "ownerId", "demo-user"),
            Map.of("id", "other-owner", "name", "Private", "score", 10, "active", true, "tenantId", "tenant-a", "ownerId", "other-user"),
            Map.of("id", "other-tenant", "name", "Secret", "score", 99, "active", true, "tenantId", "tenant-b", "ownerId", "demo-user"),
            Map.of("id", "own-a", "name", "Alpha", "score", 2, "active", true, "tenantId", "tenant-a", "ownerId", "demo-user")
        );
    }
}
