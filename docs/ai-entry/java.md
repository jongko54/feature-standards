# Optional Java SDK connection

If you choose the original SDKs, start with [the controller](../../examples/core-java/src/main/java/dev/featurestandards/examples/core/CoreController.java), [app wiring](../../examples/core-java/src/main/java/dev/featurestandards/examples/core/CoreApplication.java), [consumer manifest](../../examples/core-java/pom.xml) and [focused brief](../ai-briefs/java.md). These are optional connection hints; the task defines behavior and the implementation approach remains yours.

## Dependency and import boundary

The consumer uses JDK 21 and Spring Boot 3.5.16. Its runtime libraries are:

```xml
<dependency>
  <groupId>io.github.jongko54</groupId>
  <artifactId>java-spring-auth</artifactId>
  <version>1.0.0</version>
  <classifier>library</classifier>
</dependency>
<dependency>
  <groupId>io.github.jongko54</groupId>
  <artifactId>feature-standards-core</artifactId>
  <version>0.1.0</version>
</dependency>
```

The [auth POM](../../implementations/java-spring/pom.xml) attaches a plain `library` classifier JAR, excluding the reference `AuthApplication` and `application.properties`. The executable `auth-server.jar` and a `sources` JAR serve different purposes. The [core POM](../../libraries/java/pom.xml) produces a plain JAR without a Spring runtime dependency.

Maven coordinates do not identify which checkout produced a JAR. The [consumer README](../../examples/core-java/README.md) describes installing both original source projects into an isolated Maven repository before resolving these coordinates; it also distinguishes registry resolution. App-local copied classes with the same package names are a different runtime origin. The loaded classes' protection-domain code-source locations distinguish dependency JARs from local classes.

```java
import dev.featurestandards.auth.AuthConfig;
import dev.featurestandards.auth.AuthFilter;
import dev.featurestandards.auth.AuthService;
import dev.featurestandards.core.authorization.AuthorizationPolicy;
import dev.featurestandards.core.authorization.Grant;
import dev.featurestandards.core.authorization.Principal;
import dev.featurestandards.core.authorization.Resource;
import dev.featurestandards.core.listing.Listing;
```

## Read composition

The consumer's controller/provider interfaces are app glue, not SDK exports. Their sequence applies to other resources and schemas:

1. Share the existing `AuthService` between auth and product handlers. A new service can use `AuthService.create(config, memoryPassword, clock)`; `new AuthFilter(config, service)` is registered for `/auth/*` and `/healthz`, while the product controller handles its own routes.
2. Resolve the `fs_session` cookie with `auth.session(token)`; null is unauthenticated. Load current trusted membership from `session.user()` and compare its `Principal.subjectId()` with the original `session.user().id()`. Missing/mismatched membership denies; provider failure closes access.
3. `new AuthorizationPolicy(List.of(new Grant(role, permission, scope), ...))` defines explicit grants. Collection access uses `policy.decide(principal, listPermission, new Resource(principal.tenantId(), null)).allowed()`.
4. Each row's read permission uses `new Resource(rowTenant, rowOwner)` from trusted resource data. Keep visible rows and project public fields before totals or list processing.
5. `new Listing.Schema(sortFields, filterFields)` accepts typed `Map<String, String>` allowlists. Pass `request.getQueryString()` unchanged, substituting `""` for null, to `Listing.parseQuery(raw, schema)`; return `Listing.page(visible, query, schema)` through `ResponseEntity`.
6. Item reads share the same membership/row policy; the example denies absent and inaccessible IDs alike. It maps `Listing.Error` query failures to 400, trusted data/schema failures to generic 500, and storage failures to generic 503. Its product filter supplies `no-store`/`nosniff` on successes and errors.

Permission names, grants, fields and projections belong to the task. Current membership/resources come from server providers, rather than browser subject/tenant/role claims; the demo document model is only an example.

Custom unsafe product routes do not inherit Origin/CSRF checks from the auth filter. `AuthService.session` exposes `Session.csrfToken()`, but there is no dedicated non-destructive mutation-CSRF checker; `logout(token, csrf)` validates and destroys the session.

API detail: [auth service](../../implementations/java-spring/src/main/java/dev/featurestandards/auth/AuthService.java), [auth filter](../../implementations/java-spring/src/main/java/dev/featurestandards/auth/AuthFilter.java), [core API](../../libraries/java/README.md), [common scope](README.md).
