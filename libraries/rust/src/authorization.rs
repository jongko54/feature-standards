//! Deny-by-default rbac-v1. Supply identity and roles from trusted providers.
use std::collections::HashSet;
use std::fmt;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuthorizationError;
impl AuthorizationError {
    pub fn code(&self) -> &'static str {
        "INVALID_AUTHORIZATION_POLICY"
    }
}
impl fmt::Display for AuthorizationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for AuthorizationError {}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Principal {
    pub subject_id: String,
    pub tenant_id: String,
    pub roles: Vec<String>,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Resource {
    pub tenant_id: String,
    pub owner_id: Option<String>,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Grant {
    pub role: String,
    pub permission: String,
    pub scope: String,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Decision {
    pub allowed: bool,
    pub code: &'static str,
}
#[derive(Debug, Clone)]
pub struct Policy {
    grants: Vec<Grant>,
}

fn valid_identifier(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=64).contains(&bytes.len())
        && bytes[0].is_ascii_alphanumeric()
        && bytes[1..]
            .iter()
            .all(|c| c.is_ascii_alphanumeric() || b"._:-".contains(c))
}
fn valid_role(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=64).contains(&bytes.len())
        && bytes[0].is_ascii_lowercase()
        && bytes[1..]
            .iter()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || b"_-".contains(c))
}
fn valid_permission(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=64).contains(&bytes.len())
        && bytes[0].is_ascii_lowercase()
        && bytes[1..]
            .iter()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || b"_.:-".contains(c))
}
impl Policy {
    pub fn new(grants: Vec<Grant>) -> Result<Self, AuthorizationError> {
        if grants.len() > 256 {
            return Err(AuthorizationError);
        }
        let mut seen = HashSet::new();
        for grant in &grants {
            if !valid_role(&grant.role)
                || !valid_permission(&grant.permission)
                || !matches!(grant.scope.as_str(), "tenant" | "owner")
                || !seen.insert((&grant.role, &grant.permission))
            {
                return Err(AuthorizationError);
            }
        }
        Ok(Self { grants })
    }
    pub fn decide(
        &self,
        principal: Option<&Principal>,
        permission: &str,
        resource: &Resource,
    ) -> Decision {
        let Some(principal) = principal else {
            return Decision {
                allowed: false,
                code: "UNAUTHENTICATED",
            };
        };
        let deny = Decision {
            allowed: false,
            code: "FORBIDDEN",
        };
        if !valid_identifier(&principal.subject_id)
            || !valid_identifier(&principal.tenant_id)
            || principal.roles.len() > 16
            || !valid_permission(permission)
            || !valid_identifier(&resource.tenant_id)
            || resource
                .owner_id
                .as_ref()
                .is_some_and(|owner| !valid_identifier(owner))
            || principal.tenant_id != resource.tenant_id
        {
            return deny;
        }
        let mut roles = HashSet::new();
        for role in &principal.roles {
            if !valid_role(role) || !roles.insert(role.as_str()) {
                return deny;
            }
        }
        if self.grants.iter().any(|grant| {
            roles.contains(grant.role.as_str())
                && grant.permission == permission
                && (grant.scope == "tenant"
                    || resource.owner_id.as_deref() == Some(principal.subject_id.as_str()))
        }) {
            Decision {
                allowed: true,
                code: "ALLOWED",
            }
        } else {
            deny
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;
    fn string(value: &Value, key: &str) -> String {
        value[key].as_str().unwrap().to_owned()
    }
    #[test]
    fn shared_vectors() {
        let fixture: Value = serde_json::from_str(include_str!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/tests/fixtures/authorization.json"
        )))
        .unwrap();
        for case in fixture["cases"].as_array().unwrap() {
            let grants = case["grants"]
                .as_array()
                .unwrap()
                .iter()
                .map(|grant| Grant {
                    role: string(grant, "role"),
                    permission: string(grant, "permission"),
                    scope: string(grant, "scope"),
                })
                .collect();
            let policy = Policy::new(grants);
            if let Some(code) = case["expected"]["error"].as_str() {
                assert_eq!(policy.unwrap_err().code(), code, "{}", case["id"]);
                continue;
            }
            let principal = if case["principal"].is_null() {
                None
            } else {
                Some(Principal {
                    subject_id: string(&case["principal"], "subjectId"),
                    tenant_id: string(&case["principal"], "tenantId"),
                    roles: case["principal"]["roles"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .map(|role| role.as_str().unwrap().to_owned())
                        .collect(),
                })
            };
            let resource = Resource {
                tenant_id: string(&case["resource"], "tenantId"),
                owner_id: case["resource"]["ownerId"].as_str().map(str::to_owned),
            };
            let decision = policy.unwrap().decide(
                principal.as_ref(),
                case["permission"].as_str().unwrap(),
                &resource,
            );
            assert_eq!(
                serde_json::json!({"allowed":decision.allowed,"code":decision.code}),
                case["expected"],
                "{}",
                case["id"]
            );
        }
    }
    #[test]
    fn policy_owns_its_snapshot() {
        let mut grants = vec![Grant {
            role: "viewer".into(),
            permission: "documents:read".into(),
            scope: "tenant".into(),
        }];
        let policy = Policy::new(grants.clone()).unwrap();
        grants[0].scope = "owner".into();
        let principal = Principal {
            subject_id: "alice".into(),
            tenant_id: "tenant-a".into(),
            roles: vec!["viewer".into()],
        };
        let resource = Resource {
            tenant_id: "tenant-a".into(),
            owner_id: None,
        };
        assert!(
            policy
                .decide(Some(&principal), "documents:read", &resource)
                .allowed
        );
    }
}
