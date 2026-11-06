package authorization

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestSharedVectors(t *testing.T) {
	_, filename, _, _ := runtime.Caller(0)
	data, err := os.ReadFile(filepath.Join(filepath.Dir(filename), "../../../features/authorization/scenarios.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Cases []struct {
			ID         string     `json:"id"`
			Grants     []Grant    `json:"grants"`
			Principal  *Principal `json:"principal"`
			Permission string     `json:"permission"`
			Resource   Resource   `json:"resource"`
			Expected   struct {
				Allowed bool   `json:"allowed"`
				Code    string `json:"code"`
				Error   string `json:"error"`
			} `json:"expected"`
		} `json:"cases"`
	}
	if err = json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	for _, c := range fixture.Cases {
		t.Run(c.ID, func(t *testing.T) {
			policy, err := NewPolicy(c.Grants)
			if c.Expected.Error != "" {
				if err == nil || err.Error() != c.Expected.Error {
					t.Fatalf("expected %s, got %v", c.Expected.Error, err)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			got := policy.Decide(c.Principal, c.Permission, c.Resource)
			want := Decision{c.Expected.Allowed, c.Expected.Code}
			if got != want {
				t.Fatalf("got %+v want %+v", got, want)
			}
		})
	}
}
func TestPolicySnapshotsInput(t *testing.T) {
	grants := []Grant{{"viewer", "documents:read", "tenant"}}
	policy, err := NewPolicy(grants)
	if err != nil {
		t.Fatal(err)
	}
	grants[0].Scope = "owner"
	principal := &Principal{"alice", "tenant-a", []string{"viewer"}}
	if !policy.Decide(principal, "documents:read", Resource{TenantID: "tenant-a"}).Allowed {
		t.Fatal("policy changed with caller input")
	}
}
func TestZeroPolicyDenies(t *testing.T) {
	p := &Policy{}
	if p.Decide(&Principal{"alice", "tenant-a", []string{"viewer"}}, "documents:read", Resource{TenantID: "tenant-a"}).Allowed {
		t.Fatal("zero policy allowed")
	}
	var absent *Policy
	if absent.Decide(&Principal{"alice", "tenant-a", []string{"viewer"}}, "documents:read", Resource{TenantID: "tenant-a"}).Code != "FORBIDDEN" {
		t.Fatal("nil policy must fail closed")
	}
}
