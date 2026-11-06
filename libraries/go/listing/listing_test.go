package listing

import (
	"encoding/json"
	"errors"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"testing"
)

func testSchema(t *testing.T) *Schema {
	t.Helper()
	s, err := NewSchema(map[string]string{"id": "string", "name": "string", "count": "integer", "active": "boolean"}, map[string]string{"name": "string", "count": "integer", "active": "boolean"})
	if err != nil {
		t.Fatal(err)
	}
	return s
}
func code(t *testing.T, err error, want string) {
	t.Helper()
	var e *Error
	if !errors.As(err, &e) || e.Code != want || err.Error() != want {
		t.Fatalf("got error %v, want %s", err, want)
	}
}
func TestSharedVectors(t *testing.T) {
	_, file, _, _ := runtime.Caller(0)
	raw, err := os.ReadFile(filepath.Join(filepath.Dir(file), "../../../features/listing/scenarios.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Cases []struct {
			ID     string `json:"id"`
			Schema struct {
				SortFields   map[string]string `json:"sortFields"`
				FilterFields map[string]string `json:"filterFields"`
			} `json:"schema"`
			Query    string           `json:"query"`
			Items    []map[string]any `json:"items"`
			Expected json.RawMessage  `json:"expected"`
		} `json:"cases"`
	}
	if err = json.Unmarshal(raw, &fixture); err != nil {
		t.Fatal(err)
	}
	for _, c := range fixture.Cases {
		t.Run(c.ID, func(t *testing.T) {
			s, e := NewSchema(c.Schema.SortFields, c.Schema.FilterFields)
			var result Result
			if e == nil {
				var query Query
				query, e = ParseQuery(c.Query, s)
				if e == nil {
					result, e = Page(c.Items, query, s)
				}
			}
			var expected struct {
				Error string `json:"error"`
			}
			if err := json.Unmarshal(c.Expected, &expected); err != nil {
				t.Fatal(err)
			}
			if expected.Error != "" {
				code(t, e, expected.Error)
				return
			}
			if e != nil {
				t.Fatal(e)
			}
			actual, _ := json.Marshal(result)
			var a, b any
			_ = json.Unmarshal(actual, &a)
			_ = json.Unmarshal(c.Expected, &b)
			if !reflect.DeepEqual(a, b) {
				t.Fatalf("got %s want %s", actual, c.Expected)
			}
		})
	}
}
func TestSnapshotAndStablePagination(t *testing.T) {
	fields := map[string]string{"id": "string", "count": "integer"}
	s, err := NewSchema(fields, map[string]string{})
	if err != nil {
		t.Fatal(err)
	}
	fields["id"] = "integer"
	rows := []map[string]any{{"id": "b", "count": 2}, {"id": "a", "count": 2}, {"id": "c", "count": 1}}
	q, err := ParseQuery("sort=-count&limit=1", s)
	if err != nil {
		t.Fatal(err)
	}
	q.Limit = 10000
	q.Filters["count"] = false
	result, err := Page(rows, q, s)
	if err != nil {
		t.Fatal(err)
	}
	if result.Items[0]["id"] != "a" || result.Limit != 1 || result.NextOffset == nil || *result.NextOffset != 1 || rows[0]["id"] != "b" {
		t.Fatalf("unexpected result %+v", result)
	}
}
func TestStrictNativeEdges(t *testing.T) {
	s := testSchema(t)
	for _, raw := range []string{"filter.name=" + string([]byte{0xff}), "filter.name=%ED%A0%80", "filter.name=x%0A", "sort=id\n", "limit=1&limit=2"} {
		_, err := ParseQuery(raw, s)
		code(t, err, "INVALID_LIST_QUERY")
	}
	q, _ := ParseQuery("sort=count", s)
	for _, value := range []any{math.NaN(), math.Inf(1), true, 9007199254740992.0, nil} {
		_, err := Page([]map[string]any{{"id": "a", "count": value}}, q, s)
		code(t, err, "INVALID_LIST_DATA")
	}
	_, err := Page(nil, Query{}, s)
	code(t, err, "INVALID_LIST_QUERY")
	many := make([]map[string]any, 10001)
	q, _ = ParseQuery("", s)
	_, err = Page(many, q, s)
	code(t, err, "INVALID_LIST_DATA")
}
