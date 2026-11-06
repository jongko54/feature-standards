# Feature Standards Core — go

Unpublished experimental 0.1.0 source APIs for `authorization/rbac-v1` and `listing/offset-list-v1`. Authentication remains in its existing package. These modules implement the [shared normative contracts](../../docs/core-standards.md).

```go
import "github.com/jongko54/feature-standards/libraries/go/authorization"
import "github.com/jongko54/feature-standards/libraries/go/listing"
```

Use a local `replace github.com/jongko54/feature-standards/libraries/go => /path/to/feature-standards/libraries/go` in a consumer. `authorization.NewPolicy` creates immutable grants; `Policy.Decide` consumes server-owned Principal and Resource. `listing.NewSchema`, `ParseQuery`, and `Page` operate on typed map records. Check returned errors; never treat a failed parse/policy constructor as an allow. Go 1.26, standard library only.

Run both native feature suites from the repository root:

```sh
python3 tools/check_core_features.py --stack go --feature all
```

Each native test suite consumes `features/authorization/scenarios.json` and `features/listing/scenarios.json`; source-checkout tests intentionally use repository-relative fixture paths. Runtime consumers do not need those fixture files. Apply trusted current membership, server resource tenant/owner, deny-by-default policy, and authorization scoping before listing totals. Listing accepts only bounded materialized data, exact filters, and a strict raw query string. No production audit, database adapter or registry release is implied.
