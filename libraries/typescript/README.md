# Feature Standards Core — typescript

Experimental 0.1.0 APIs for `authorization/rbac-v1` and `listing/offset-list-v1`. Authentication remains in its existing package. These modules implement the [shared normative contracts](https://github.com/jongko54/feature-standards/blob/main/docs/core-standards.md).

After publication: `npm install @ugauga/feature-standards-core@0.1.0`. Before publication, use a local directory dependency. ES modules and `.d.mts` declarations are provided without a build step or runtime dependency. Node >=22.12 runs the tests; browser consumers can use their normal bundler.

```js
import { Grant, Policy, Principal, Resource, createListingSchema, parseListQuery, listPage } from '@ugauga/feature-standards-core';
const policy = new Policy([new Grant('viewer', 'documents:read', 'owner')]);
const decision = policy.decide(new Principal('user-1', 'tenant-a', ['viewer']), 'documents:read', new Resource('tenant-a', 'user-1'));
const schema = createListingSchema({sortFields: {id: 'string'}, filterFields: {}});
const result = listPage([{id: 'a'}], parseListQuery('limit=20', schema), schema);
```

Browser authorization is advisory: never rely on it to protect server data. This library supports React consumers without depending on React and does not add a new UI. The npm package is `@ugauga/feature-standards-core`; registry publication is tracked separately from source readiness.

Run both native feature suites from the repository root:

```sh
python3 tools/check_core_features.py --stack react --feature all
```

Each native test suite consumes `features/authorization/scenarios.json` and `features/listing/scenarios.json`; source-checkout tests intentionally use repository-relative fixture paths. Runtime consumers do not need those fixture files. Apply trusted current membership, server resource tenant/owner, deny-by-default policy, and authorization scoping before listing totals. Listing accepts only bounded materialized data, exact filters, and a strict raw query string. No production audit or database adapter is implied. Check the repository release receipts for actual registry availability.
