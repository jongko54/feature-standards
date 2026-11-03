package dev.featurestandards.examples;

import dev.featurestandards.auth.AuthConfig;
import dev.featurestandards.auth.AuthFilter;
import dev.featurestandards.auth.AuthService;
import java.time.Clock;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.core.Ordered;
import org.springframework.core.env.Environment;

/** Consumer-owned wiring; all authentication behavior comes from the library JAR. */
@SpringBootApplication
public class ConsumerApplication {
    public static void main(String[] args) {
        SpringApplication.run(ConsumerApplication.class, args);
    }

    @Bean AuthConfig authConfig(Environment env) { return AuthConfig.load(env::getProperty); }

    @Bean AuthService authService(AuthConfig config, Environment env) {
        return AuthService.create(config, config.store().equals("postgres") ? null
                : AuthConfig.password(env::getProperty, config.demo()), Clock.systemUTC());
    }

    @Bean FilterRegistrationBean<AuthFilter> authFilter(AuthConfig config, AuthService service) {
        var bean = new FilterRegistrationBean<>(new AuthFilter(config, service));
        // AuthFilter owns these paths. Consumer controllers own /api and other routes.
        bean.addUrlPatterns("/auth/*", "/healthz");
        bean.setOrder(Ordered.HIGHEST_PRECEDENCE);
        return bean;
    }
}
