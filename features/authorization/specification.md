# Authorization: rbac-v1

Status: experimental source contract, version 1. This profile is independent of authentication. All requirements below are normative.


- Server-owned principal `{subjectId, tenantId, roles}`; nullable principal means anonymous. Server-owned resource `{tenantId, ownerId}`; owner may be absent/null for collection scope.
- Immutable policy snapshot constructed from at most 256 grants `{role, permission, scope}`. Scopes are exactly `tenant` or `owner`; no wildcards, hierarchy, implicit administrator, deny overrides, or policy management API.
- Policy validates every grant, rejects duplicate `(role,permission)` pairs (including identical duplicates), and copies caller-owned input. Invalid policy construction is `INVALID_AUTHORIZATION_POLICY`.
- Identifier grammar: subject/tenant/non-null owner `[A-Za-z0-9][A-Za-z0-9._:-]{0,63}`; role `[a-z][a-z0-9_-]{0,63}`; permission `[a-z][a-z0-9_.:-]{0,63}`. Principal roles: at most 16 unique values. Empty roles are valid and deny. Empty policy is valid and denies.
- `Policy.decide(principal, permission, resource)` returns `{allowed,code}`. Null principal returns false/UNAUTHENTICATED. Invalid principal, permission or resource returns false/FORBIDDEN. Unknown roles/permissions deny unless another explicit matching role grants access.
- Tenant mismatch always denies, even for roles named admin. `owner` additionally requires non-null matching ownerId; `tenant` permits a matching tenant with optional owner. Success is true/ALLOWED; all other authenticated decisions are false/FORBIDDEN.
- HTTP consumer authenticates with the real existing session, then loads current membership and resources from server-owned providers on each request. No role/tenant/subject from headers/query/body is trusted. Membership failure is generic 503 AUTHORIZATION_UNAVAILABLE. GET-only product examples avoid inventing a mutation-CSRF helper. List visibility is filtered with the same policy before pagination or totals.
- Browser helpers may assist presentation only. Native server policy remains authoritative.


## HTTP composition

The separate Python consumer exposes `GET /api/documents/{document_id}`. Authenticate first, obtain the current principal from a trusted membership provider, load the resource from the server, then decide `documents:read`. Allowed requests return the document (200). Anonymous sessions return 401 UNAUTHENTICATED; absent or inaccessible resources return 403 FORBIDDEN to avoid a resource existence oracle. Membership-provider failure returns 503 AUTHORIZATION_UNAVAILABLE. Incomplete trusted product data returns 500 INVALID_LIST_DATA. Responses are no-store. There is no public authorization decision endpoint and no trusted role header.

## Executable contract

`scenarios.json` is a language-neutral fixture executed by all five native test suites. Native tests additionally verify policy snapshots and language-specific input handling. Run `python3 tools/check_core_features.py --feature authorization --stack all`. See [composition guide](../../docs/core-standards.md).
