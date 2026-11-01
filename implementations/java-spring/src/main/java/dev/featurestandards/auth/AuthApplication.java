package dev.featurestandards.auth;

import java.time.Clock;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.core.Ordered;
import org.springframework.core.env.Environment;

@SpringBootApplication
public class AuthApplication {
    public static void main(String[] args) {
        // Validate before Tomcat binds. Only AUTH_* variables define this reference profile.
        AuthConfig config = AuthConfig.load(System::getenv);
        var app = new SpringApplication(AuthApplication.class);
        app.addInitializers(context -> context.getEnvironment().getPropertySources().addFirst(
                new org.springframework.core.env.MapPropertySource("auth-bind",
                        java.util.Map.of("server.address", config.host(), "server.port", config.port()))));
        app.run(args);
    }
    @Bean AuthConfig authConfig(Environment env) { return AuthConfig.load(env::getProperty); }
    @Bean AuthService authService(AuthConfig config, Environment env) {
        return new AuthService(config, AuthConfig.password(env::getProperty, config.demo()), Clock.systemUTC());
    }
    @Bean FilterRegistrationBean<AuthFilter> authFilter(AuthConfig config, AuthService service) {
        var bean = new FilterRegistrationBean<>(new AuthFilter(config, service));
        bean.addUrlPatterns("/*");
        bean.setOrder(Ordered.HIGHEST_PRECEDENCE);
        return bean;
    }
}
