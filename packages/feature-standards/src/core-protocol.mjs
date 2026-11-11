/** Shared starter metadata/receipt contract. Importing it performs no I/O. */
export const CORE_CHECK_PROTOCOL_VERSION = 1;
export const CORE_FEATURES = Object.freeze(['auth', 'authorization', 'listing']);
export const CORE_PROFILES = Object.freeze({ auth: 'browser-session-v1', authorization: 'rbac-v1', listing: 'offset-list-v1' });
export const CORE_REQUIRED_CHECKS = Object.freeze([
  'selected-profile-health',
  'actual-sdk-dependency-origins',
  'normal-start-denies-sample-access',
  'anonymous-and-forged-protected-access',
  'login-shared-protected-identity',
  'independent-sessions',
  'origin-and-csrf-rejection',
  'owner-and-tenant-isolation',
  'authorization-before-list-totals',
  'typed-filter-sort-pagination',
  'strict-raw-query-errors',
  'logout-revokes-copied-cookie',
]);
export const CORE_AUTH_ROOTS = Object.freeze({ python: 'implementations/python-fastapi', go: 'implementations/go-net-http', java: 'implementations/java-spring', rust: 'implementations/rust-axum' });
export const CORE_STACKS = Object.freeze(Object.keys(CORE_AUTH_ROOTS));
export const CORE_MANIFESTS = Object.freeze(['features/catalog.json', 'feature-standards.json', 'features/authorization/catalog.json', 'features/listing/catalog.json']);
