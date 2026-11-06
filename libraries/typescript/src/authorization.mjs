/** Advisory browser decisions. Always enforce the same policy on the server. */
const identifier = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}/u;
const rolePattern = /^[a-z][a-z0-9_-]{0,63}/u;
const permissionPattern = /^[a-z][a-z0-9_.:-]{0,63}/u;
// Comparing the full match avoids JavaScript's pre-final-newline `$` behavior.
const matches = (value, pattern) => typeof value === 'string' && pattern.exec(value)?.[0] === value;
const denied = Object.freeze({ allowed: false, code: 'FORBIDDEN' });
const anonymous = Object.freeze({ allowed: false, code: 'UNAUTHENTICATED' });
const allowed = Object.freeze({ allowed: true, code: 'ALLOWED' });

export class AuthorizationError extends Error {
  constructor() { super('INVALID_AUTHORIZATION_POLICY'); this.name = 'AuthorizationError'; this.code = 'INVALID_AUTHORIZATION_POLICY'; }
}
export class Principal {
  constructor(subjectId, tenantId, roles) {
    this.subjectId = subjectId; this.tenantId = tenantId;
    this.roles = Array.isArray(roles) ? Object.freeze([...roles]) : roles;
    Object.freeze(this);
  }
}
export class Resource {
  constructor(tenantId, ownerId = null) { this.tenantId = tenantId; this.ownerId = ownerId; Object.freeze(this); }
}
export class Grant {
  constructor(role, permission, scope) { this.role = role; this.permission = permission; this.scope = scope; Object.freeze(this); }
}
export class Policy {
  #grants;
  constructor(grants) {
    if (!Array.isArray(grants) || grants.length > 256) throw new AuthorizationError();
    const seen = new Set();
    this.#grants = Object.freeze(Array.from(grants, grant => {
      if (!(grant instanceof Grant) || !matches(grant.role, rolePattern)
          || !matches(grant.permission, permissionPattern) || !['tenant', 'owner'].includes(grant.scope)) {
        throw new AuthorizationError();
      }
      const key = `${grant.role}\0${grant.permission}`;
      if (seen.has(key)) throw new AuthorizationError();
      seen.add(key);
      return new Grant(grant.role, grant.permission, grant.scope);
    }));
    Object.freeze(this);
  }
  decide(principal, permission, resource) {
    if (principal === null) return anonymous;
    if (!(principal instanceof Principal) || !matches(principal.subjectId, identifier)
        || !matches(principal.tenantId, identifier) || !Array.isArray(principal.roles)
        || principal.roles.length > 16 || !principal.roles.every(role => matches(role, rolePattern))
        || new Set(principal.roles).size !== principal.roles.length || !matches(permission, permissionPattern)
        || !(resource instanceof Resource) || !matches(resource.tenantId, identifier)
        || (resource.ownerId !== null && !matches(resource.ownerId, identifier))
        || principal.tenantId !== resource.tenantId) return denied;
    return this.#grants.some(grant => principal.roles.includes(grant.role) && grant.permission === permission
      && (grant.scope === 'tenant' || resource.ownerId === principal.subjectId)) ? allowed : denied;
  }
}
