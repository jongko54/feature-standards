# Feature Standards Core — java

Experimental 0.1.0 APIs for `authorization/rbac-v1` and `listing/offset-list-v1`. Authentication remains in its existing package. These modules implement the [shared normative contracts](https://github.com/jongko54/feature-standards/blob/main/docs/core-standards.md).

Build with JDK 21: `implementations/java-spring/mvnw -f libraries/java/pom.xml install`. This is a plain JAR with no Spring runtime dependency. The local artifact is `io.github.jongko54:feature-standards-core:0.1.0`; its publication is tracked in the release receipts.

Public APIs: `dev.featurestandards.core.authorization.AuthorizationPolicy` plus Principal/Resource/Grant/Decision records, and `dev.featurestandards.core.listing.Listing` with Schema/Query and `parseQuery`/`page`. Unit tests provide complete importable examples and execute the common JSON vectors. Jackson is a test dependency only.

Run both native feature suites from the repository root:

```sh
python3 tools/check_core_features.py --stack java --feature all
```

Each native test suite consumes `features/authorization/scenarios.json` and `features/listing/scenarios.json`; source-checkout tests intentionally use repository-relative fixture paths. Runtime consumers do not need those fixture files. Apply trusted current membership, server resource tenant/owner, deny-by-default policy, and authorization scoping before listing totals. Listing accepts only bounded materialized data, exact filters, and a strict raw query string. No production audit or database adapter is implied. Check the repository release receipts for actual registry availability.
