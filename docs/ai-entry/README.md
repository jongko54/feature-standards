# Optional SDK connection cards

These cards are a short entry point if you choose the original Feature Standards SDKs for session authentication, explicit permissions and bounded materialized listing. Using a dependency, reusing source, or implementing the requested behavior directly remains an application choice. The cards do not add task requirements or require particular APIs.

| Backend | Connection card | Working HTTP composition |
| --- | --- | --- |
| Python / FastAPI | [Python](python.md) | [core-python](../../examples/core-python/app.py) |
| Go / net/http | [Go](go.md) | [core-go](../../examples/core-go/main.go) |
| Java / Spring | [Java](java.md) | [core-java](../../examples/core-java/src/main/java/dev/featurestandards/examples/core/CoreController.java) |
| Rust / Axum | [Rust](rust.md) | [core-rust](../../examples/core-rust/src/lib.rs) |

The examples happen to use documents. Their composition also applies to other business resources: select the task's permission names, grants, typed sort/filter fields, resource attributes and public response fields. Demo users, roles and records describe those examples rather than the target application's data model.

For an SDK-backed read, the common flow is: shared auth session → current trusted membership with the same subject → collection grant → each row's read visibility → public projection → original raw query and typed schema → list response. Visibility precedes totals, filtering, sorting and paging. The application owns membership/resource loading, response projection and route error handling.

The target product contract also owns its error envelope. SDK identity helpers use their auth contract's fixed messages; those messages differ across languages and need not equal a product's required message. When a product requires `{"error":{"code":"FIXED_CODE","message":"Request could not be completed."}}`, normalize SDK identity failures at the product boundary while preserving the status, an allowlisted error code and required security headers. The stack cards explain where errors are raised or written. The linked consumers demonstrate composition; they are not complete implementations of every target contract.

The cards describe `browser-session-v1`, `rbac-v1` and `offset-list-v1`. Existing authentication settings and profiles belong to the target application. Materialized listing handles at most 10,000 records; it is not a database pagination adapter. The HTTP examples add GET routes; custom state-changing routes need their own Origin, session-CSRF and permission enforcement.

Paths identify this source checkout. An external checkout dependency, a registry artifact and an app-local vendored copy can expose the same API names while loading different runtime source. Dependency metadata and actual module/JAR origins distinguish them; none updates automatically when another source changes. The [core release receipt](../core-release-0.1.0.json) records historical registry checks, while source manifests describe this checkout.

For more detail, see the [stack briefs](../ai-briefs/), [auth contract](../../features/auth/specification.md), [authorization contract](../../features/authorization/specification.md), [listing contract](../../features/listing/specification.md), [auth integration skill](../../skills/integrate-auth/SKILL.md) and [core integration skill](../../skills/integrate-core/SKILL.md).
