/** Browser policy decisions are advisory. Server enforcement is required. */
export type Decision = Readonly<{ allowed: boolean; code: 'ALLOWED' | 'FORBIDDEN' | 'UNAUTHENTICATED' }>;
export type Scope = 'tenant' | 'owner';
export declare class AuthorizationError extends Error { readonly code: 'INVALID_AUTHORIZATION_POLICY'; }
export declare class Principal {
  readonly subjectId: string; readonly tenantId: string; readonly roles: readonly string[];
  constructor(subjectId: string, tenantId: string, roles: readonly string[]);
}
export declare class Resource {
  readonly tenantId: string; readonly ownerId: string | null;
  constructor(tenantId: string, ownerId?: string | null);
}
export declare class Grant {
  readonly role: string; readonly permission: string; readonly scope: Scope;
  constructor(role: string, permission: string, scope: Scope);
}
export declare class Policy {
  constructor(grants: readonly Grant[]);
  decide(principal: Principal | null, permission: string, resource: Resource): Decision;
}
