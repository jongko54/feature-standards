// Package authorization implements deny-by-default rbac-v1 decisions.
// Principal and resource identity must come from trusted server-side providers.
package authorization

import "regexp"

var identifier = regexp.MustCompile(`\A[A-Za-z0-9][A-Za-z0-9._:-]{0,63}\z`)
var rolePattern = regexp.MustCompile(`\A[a-z][a-z0-9_-]{0,63}\z`)
var permissionPattern = regexp.MustCompile(`\A[a-z][a-z0-9_.:-]{0,63}\z`)

type AuthorizationError struct{}

func (AuthorizationError) Error() string { return "INVALID_AUTHORIZATION_POLICY" }
func (AuthorizationError) Code() string  { return "INVALID_AUTHORIZATION_POLICY" }

type Principal struct {
	SubjectID string   `json:"subjectId"`
	TenantID  string   `json:"tenantId"`
	Roles     []string `json:"roles"`
}
type Resource struct {
	TenantID string  `json:"tenantId"`
	OwnerID  *string `json:"ownerId"`
}
type Grant struct {
	Role       string `json:"role"`
	Permission string `json:"permission"`
	Scope      string `json:"scope"`
}
type Decision struct {
	Allowed bool   `json:"allowed"`
	Code    string `json:"code"`
}

// Policy owns an immutable snapshot; its fields cannot be mutated by consumers.
type Policy struct{ grants []Grant }

func NewPolicy(grants []Grant) (*Policy, error) {
	if len(grants) > 256 {
		return nil, AuthorizationError{}
	}
	seen := make(map[[2]string]bool)
	copied := make([]Grant, 0, len(grants))
	for _, grant := range grants {
		key := [2]string{grant.Role, grant.Permission}
		if !rolePattern.MatchString(grant.Role) || !permissionPattern.MatchString(grant.Permission) ||
			(grant.Scope != "tenant" && grant.Scope != "owner") || seen[key] {
			return nil, AuthorizationError{}
		}
		seen[key] = true
		copied = append(copied, grant)
	}
	return &Policy{grants: copied}, nil
}
func (policy *Policy) Decide(principal *Principal, permission string, resource Resource) Decision {
	if principal == nil {
		return Decision{false, "UNAUTHENTICATED"}
	}
	deny := Decision{false, "FORBIDDEN"}
	if policy == nil || !identifier.MatchString(principal.SubjectID) || !identifier.MatchString(principal.TenantID) ||
		len(principal.Roles) > 16 || !permissionPattern.MatchString(permission) || !identifier.MatchString(resource.TenantID) ||
		(resource.OwnerID != nil && !identifier.MatchString(*resource.OwnerID)) || principal.TenantID != resource.TenantID {
		return deny
	}
	roles := make(map[string]bool)
	for _, role := range principal.Roles {
		if !rolePattern.MatchString(role) || roles[role] {
			return deny
		}
		roles[role] = true
	}
	for _, grant := range policy.grants {
		if roles[grant.Role] && grant.Permission == permission &&
			(grant.Scope == "tenant" || (resource.OwnerID != nil && *resource.OwnerID == principal.SubjectID)) {
			return Decision{true, "ALLOWED"}
		}
	}
	return deny
}
