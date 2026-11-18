# Java authentication + authorization + listing consumer

This separate Spring Boot 4.1.2 application imports the current source candidate `java-spring-auth:2.0.0:library` and the plain `feature-standards-core:0.1.0` JAR. It uses Spring 7, Servlet 6.1 and Jackson 3. It exposes `GET /api/documents` and `GET /api/documents/{id}` while the existing authentication filter owns `/auth/*`. Authentication implementation code is never copied into the application. Boot 3.x consumers must migrate the framework and container before adopting the authentication 2.0.0 source candidate.

Use JDK 21. From the repository root, verify the current source with an isolated Maven repository:

```sh
core_maven_repo="$(mktemp -d)"
implementations/java-spring/mvnw -q -Dmaven.repo.local="$core_maven_repo" -f implementations/java-spring/pom.xml -DskipTests install
implementations/java-spring/mvnw -q -Dmaven.repo.local="$core_maven_repo" -f libraries/java/pom.xml -DskipTests install
implementations/java-spring/mvnw -q -Dmaven.repo.local="$core_maven_repo" -f examples/core-java/pom.xml test
implementations/java-spring/mvnw -q -Dmaven.repo.local="$core_maven_repo" -f examples/core-java/pom.xml -DskipTests package
AUTH_DEMO=true AUTH_STORE=memory AUTH_ACCOUNT_LIFECYCLE=false AUTH_COOKIE_SECURE=false AUTH_ALLOWED_ORIGIN=http://127.0.0.1:5173 PORT=8012 java -jar examples/core-java/target/core-java.jar
```

The runnable example binds `127.0.0.1` and requires explicit memory-demo configuration. `PORT` overrides `AUTH_PORT`. The authentication 2.0.0 source candidate requires the local installation above; its availability on Maven Central is not asserted. The historical 1.0.0 authentication and 0.1.0 core publication receipts remain separate from this Spring 7 source-consumer check.

Login through `POST /auth/login` with the existing demo credentials and exact Origin. Keep the HttpOnly `fs_session` cookie for both product routes. Logout uses the existing Origin and session-CSRF contract. Product routes accept GET only and return no-store/nosniff headers, including error responses.

`MembershipProvider` is an internal application-construction dependency that loads the authenticated subject's current membership on every product request. Replace the demo provider with your real server-owned membership service when adapting the application. Missing or mismatched membership denies access; provider failure returns generic `503 AUTHORIZATION_UNAVAILABLE`. Roles, tenant and subject never come from browser headers or query parameters. `DocumentProvider` supplies server-owned resources. The policy grants tenant collection access and owner-only reads; inaccessible records are excluded before list totals, filtering, sorting or pagination. Public responses contain only `id`, `name`, `score` and `active`.

The native tests use actual loopback HTTP through Spring Boot on an owned ephemeral port. They cover cookie login/logout and old-cookie rejection, owner/tenant isolation, hidden totals, stable pagination, typed filters, strict raw-query errors, forged headers, membership revocation/failure/mismatched identities and generic trusted-data failures. Test providers are injected when constructing the application; no HTTP provider-control endpoint exists. The tests also verify that the auth and core classes are loaded from dependency JARs.

This example has bounded materialized records and no policy administration, UI or database pagination adapter. It does not establish production security certification. See [the shared contracts](../../docs/core-standards.md).
