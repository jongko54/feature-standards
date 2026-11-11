# Optional Go SDK connection

If you choose the original SDKs, start with [the working consumer](../../examples/core-go/main.go), [its manifest](../../examples/core-go/go.mod) and [the focused brief](../ai-briefs/go.md). These are optional connection hints; the task defines the application's behavior and the implementation approach remains yours.

## Dependency and import boundary

The consumer uses Go 1.26.0 and declares these module versions with source replacements:

```go
require (
    github.com/jongko54/feature-standards/implementations/go-net-http v0.1.0
    github.com/jongko54/feature-standards/libraries/go v0.1.0
)
replace github.com/jongko54/feature-standards/implementations/go-net-http => ../../implementations/go-net-http
replace github.com/jongko54/feature-standards/libraries/go => ../../libraries/go
```

These paths are relative to `examples/core-go/go.mod`; a different app can target the supplied checkout. `replace` determines the loaded source even though `require` still contains a version. A replacement into the original checkout and a replacement into an app-local copied directory have different origins. `go list -m -json all` exposes each replacement directory.

```go
import (
    "github.com/jongko54/feature-standards/implementations/go-net-http/auth"
    "github.com/jongko54/feature-standards/libraries/go/authorization"
    "github.com/jongko54/feature-standards/libraries/go/listing"
)
```

See the [auth module](../../implementations/go-net-http/go.mod) and [core module](../../libraries/go/go.mod). Import spelling alone does not establish whether code came from the checkout, module cache or a vendored copy.

## Read composition

`newHandler` and `handlerWithDocuments` are consumer-local glue, not SDK exports. Their sequence also works with other business resources:

1. Reuse one `auth.Server` for `/auth/` and product reads. A new instance comes from `auth.NewServer(config)` and is closed with `server.Close()`; the consumer mounts it on its mux.
2. `user, ok := server.CurrentUser(w, r)` resolves the real cookie session. On false, it has already written an SDK auth error, whose message is the code. If the product needs another envelope, call it with a buffering writer such as `probe := httptest.NewRecorder()` from `net/http/httptest` instead of committing to the real writer. On failure, use `probe.Code` and its allowlisted JSON `error.code` in the application's product error writer with the required fixed message and security headers; do not first forward the SDK body or write a second response. On success, continue with the returned identity and apply the product headers to the real response. Save `user["id"]`, pass a copied map to trusted current membership, and compare the returned `Principal.SubjectID` with the saved ID. Missing/mismatched membership denies; provider failure closes access.
3. `authorization.NewPolicy([]authorization.Grant{...})` declares grants. Collection access uses `policy.Decide(principal, listPermission, authorization.Resource{TenantID: principal.TenantID}).Allowed`.
4. For each row, check its read permission against trusted `Resource{TenantID: rowTenant, OwnerID: &rowOwner}`. Keep allowed rows and project public fields before totals or list processing.
5. `listing.NewSchema(sortFields, filterFields)` accepts typed `map[string]string` allowlists. Pass `r.URL.RawQuery` unchanged to `listing.ParseQuery`; then pass scoped `[]map[string]any` to `listing.Page(visible, query, schema)` and encode its result as JSON. Handle constructor/parser/page errors.
6. Item reads share the same membership/row policy; the example denies absent and inaccessible IDs alike. It maps invalid queries to 400, trusted listing failures to generic 500, and wraps every product response with `no-store`/`nosniff` headers.

The task chooses permission names, scopes, fields and projections. Server-owned membership/resource loading supplies the current tenant, owner and roles; browser claims do not replace those providers.

`CurrentUser` returns identity only. Custom unsafe routes need separate Origin and session-CSRF checks. There is no public `Server` method for non-destructive CSRF validation; an application retaining an injected `AuthStore` can call `Current(ctx, token)`, handle its error, and inspect the returned `Session.CSRF`, whereas the server's store is private. Store `Logout` validates and destroys the session.

API detail: [auth API](../../implementations/go-net-http/auth/server.go), [core API](../../libraries/go/README.md), [common scope](README.md).
