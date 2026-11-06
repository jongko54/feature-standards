"""Framework-independent, deny-by-default authorization decisions."""

from dataclasses import dataclass
import re

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
_ROLE = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_PERMISSION = re.compile(r"[a-z][a-z0-9_.:-]{0,63}")


def _matches(value, pattern):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


@dataclass(frozen=True)
class Principal:
    subject_id: str
    tenant_id: str
    roles: tuple[str, ...]

    def __post_init__(self):
        if isinstance(self.roles, (list, tuple)):
            object.__setattr__(self, "roles", tuple(self.roles))


@dataclass(frozen=True)
class Resource:
    tenant_id: str
    owner_id: str | None = None


@dataclass(frozen=True)
class Grant:
    role: str
    permission: str
    scope: str


@dataclass(frozen=True)
class Decision:
    allowed: bool
    code: str


class AuthorizationError(ValueError):
    code = "INVALID_AUTHORIZATION_POLICY"

    def __init__(self):
        super().__init__(self.code)


@dataclass(frozen=True, slots=True, init=False)
class Policy:
    _grants: tuple[Grant, ...]

    def __init__(self, grants):
        if not isinstance(grants, (list, tuple)) or len(grants) > 256:
            raise AuthorizationError()
        copied = []
        seen = set()
        for grant in grants:
            if (
                not isinstance(grant, Grant)
                or not _matches(grant.role, _ROLE)
                or not _matches(grant.permission, _PERMISSION)
                or not isinstance(grant.scope, str)
                or grant.scope not in ("tenant", "owner")
                or (grant.role, grant.permission) in seen
            ):
                raise AuthorizationError()
            seen.add((grant.role, grant.permission))
            copied.append(Grant(grant.role, grant.permission, grant.scope))
        object.__setattr__(self, "_grants", tuple(copied))

    def decide(self, principal, permission, resource):
        if principal is None:
            return Decision(False, "UNAUTHENTICATED")
        if (
            not isinstance(principal, Principal)
            or not _matches(principal.subject_id, _IDENTIFIER)
            or not _matches(principal.tenant_id, _IDENTIFIER)
            or not isinstance(principal.roles, tuple)
            or len(principal.roles) > 16
            or not all(_matches(role, _ROLE) for role in principal.roles)
            or len(set(principal.roles)) != len(principal.roles)
            or not _matches(permission, _PERMISSION)
            or not isinstance(resource, Resource)
            or not _matches(resource.tenant_id, _IDENTIFIER)
            or (resource.owner_id is not None and not _matches(resource.owner_id, _IDENTIFIER))
            or principal.tenant_id != resource.tenant_id
        ):
            return Decision(False, "FORBIDDEN")
        for grant in self._grants:
            if grant.role in principal.roles and grant.permission == permission:
                if grant.scope == "tenant" or resource.owner_id == principal.subject_id:
                    return Decision(True, "ALLOWED")
        return Decision(False, "FORBIDDEN")
