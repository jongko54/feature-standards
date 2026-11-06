"""Native authorization behavior, plus the same vectors used by every stack."""

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from feature_standards.authorization import AuthorizationError, Grant, Policy, Principal, Resource


class AuthorizationTests(unittest.TestCase):
    def test_shared_vectors(self):
        path = Path(__file__).resolve().parents[3] / "features/authorization/scenarios.json"
        for case in json.loads(path.read_text())["cases"]:
            with self.subTest(case=case["id"]):
                grants = [Grant(**grant) for grant in case["grants"]]
                if "error" in case["expected"]:
                    with self.assertRaises(AuthorizationError) as raised:
                        Policy(grants)
                    self.assertEqual(raised.exception.code, case["expected"]["error"])
                    continue
                value = case["principal"]
                principal = None if value is None else Principal(value["subjectId"], value["tenantId"], value["roles"])
                value = case["resource"]
                resource = Resource(value["tenantId"], value.get("ownerId"))
                decision = Policy(grants).decide(principal, case["permission"], resource)
                self.assertEqual({"allowed": decision.allowed, "code": decision.code}, case["expected"])

    def test_explicit_grant_allows_only_matching_tenant(self):
        policy = Policy([Grant("viewer", "documents:read", "tenant")])
        principal = Principal("alice", "tenant-a", ("viewer",))
        self.assertEqual(policy.decide(principal, "documents:read", Resource("tenant-a" )).code, "ALLOWED")
        self.assertTrue(policy.decide(principal, "documents:read", Resource("tenant-a")).allowed)
        self.assertFalse(policy.decide(principal, "documents:read", Resource("tenant-b", "alice")).allowed)

    def test_owner_grant_requires_owner_and_tenant(self):
        policy = Policy([Grant("editor", "documents:read", "owner")])
        principal = Principal("alice", "tenant-a", ("editor",))
        for tenant, owner, allowed in (("tenant-a", "alice", True), ("tenant-a", "bob", False), ("tenant-a", None, False), ("tenant-b", "alice", False)):
            with self.subTest(tenant=tenant, owner=owner):
                self.assertEqual(policy.decide(principal, "documents:read", Resource(tenant, owner)).allowed, allowed)

    def test_anonymous_and_empty_policy_deny(self):
        self.assertEqual(Policy([]).decide(None, "documents:read", Resource("tenant-a")).code, "UNAUTHENTICATED")
        self.assertEqual(Policy([]).decide(Principal("alice", "tenant-a", ("admin",)), "documents:read", Resource("tenant-a")).code, "FORBIDDEN")

    def test_policy_copies_input_and_cannot_be_mutated(self):
        grants = [Grant("viewer", "documents:read", "tenant")]
        policy = Policy(grants)
        grants.clear()
        self.assertTrue(policy.decide(Principal("alice", "tenant-a", ("viewer",)), "documents:read", Resource("tenant-a")).allowed)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            policy._grants = ()

    def test_duplicate_pairs_and_malformed_policy_rejected(self):
        invalid = [None, "viewer", [None], [Grant("Admin", "documents:read", "tenant")], [Grant("viewer", "*", "tenant")], [Grant("viewer", "documents:read", "global")], [Grant("viewer", "documents:read", "owner"), Grant("viewer", "documents:read", "tenant")], [Grant("viewer", "documents:read", "owner")]*2, [Grant(f"role{i}", "documents:read", "tenant") for i in range(257)]]
        for grants in invalid:
            with self.subTest(grants=repr(grants)[:80]):
                with self.assertRaisesRegex(AuthorizationError, "^INVALID_AUTHORIZATION_POLICY$"):
                    Policy(grants)

    def test_invalid_authenticated_inputs_fail_closed(self):
        policy = Policy([Grant("viewer", "documents:read", "tenant")])
        valid = Principal("alice", "tenant-a", ("viewer",))
        principals = [Principal("", "tenant-a", ("viewer",)), Principal("alice", "tenant-a", "viewer"), Principal("alice", "tenant-a", ("viewer", "viewer")), Principal("alice", "tenant-a", tuple(f"role{i}" for i in range(17))), Principal("alice", "tenant-a", ())]
        for principal in principals:
            decision = policy.decide(principal, "documents:read", Resource("tenant-a"))
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.code, "FORBIDDEN")
        for permission, resource in (("Documents:read", Resource("tenant-a")), ("documents:read", Resource("bad tenant")), ("documents:read", Resource("tenant-a", ""))):
            self.assertEqual(policy.decide(valid, permission, resource).code, "FORBIDDEN")


if __name__ == "__main__":
    unittest.main()
