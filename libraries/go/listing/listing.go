// Package listing implements the strict, bounded offset-list-v1 contract.
// Callers must apply authorization visibility before invoking Page.
package listing

import (
	"encoding/json"
	"math"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

const safeInteger = 9007199254740991

var fieldPattern = regexp.MustCompile(`^[a-z][a-z0-9_]{0,31}$`)
var idPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$`)
var unsignedPattern = regexp.MustCompile(`^(0|[1-9][0-9]*)$`)
var signedPattern = regexp.MustCompile(`^(0|-?[1-9][0-9]*)$`)

// Error exposes only a fixed contract code, never raw input or row data.
type Error struct{ Code string }

func (e *Error) Error() string  { return e.Code }
func failure(code string) error { return &Error{Code: code} }

// Schema is an immutable snapshot of the server's field allowlists.
type Schema struct{ sortFields, filterFields map[string]string }

func NewSchema(sortFields, filterFields map[string]string) (*Schema, error) {
	copies := []map[string]string{}
	for _, fields := range []map[string]string{sortFields, filterFields} {
		if len(fields) > 16 {
			return nil, failure("INVALID_LIST_SCHEMA")
		}
		copied := map[string]string{}
		for field, kind := range fields {
			if !fieldPattern.MatchString(field) || (kind != "string" && kind != "integer" && kind != "boolean") {
				return nil, failure("INVALID_LIST_SCHEMA")
			}
			copied[field] = kind
		}
		copies = append(copies, copied)
	}
	if copies[0]["id"] != "string" {
		return nil, failure("INVALID_LIST_SCHEMA")
	}
	for field, kind := range copies[1] {
		if previous, ok := copies[0][field]; ok && previous != kind {
			return nil, failure("INVALID_LIST_SCHEMA")
		}
	}
	return &Schema{copies[0], copies[1]}, nil
}
func validSchema(schema *Schema) bool { return schema != nil && schema.sortFields["id"] == "string" }
func text(value string) bool {
	if !utf8.ValidString(value) {
		return false
	}
	for _, point := range value {
		if point < 32 || point == 127 {
			return false
		}
	}
	return true
}
func number(value any) (float64, bool) {
	var n float64
	switch v := value.(type) {
	case int:
		n = float64(v)
	case int8:
		n = float64(v)
	case int16:
		n = float64(v)
	case int32:
		n = float64(v)
	case int64:
		if v > safeInteger || v < -safeInteger {
			return 0, false
		}
		n = float64(v)
	case uint:
		if uint64(v) > safeInteger {
			return 0, false
		}
		n = float64(v)
	case uint8:
		n = float64(v)
	case uint16:
		n = float64(v)
	case uint32:
		n = float64(v)
	case uint64:
		if v > safeInteger {
			return 0, false
		}
		n = float64(v)
	case float32:
		n = float64(v)
	case float64:
		n = v
	case json.Number:
		var err error
		n, err = strconv.ParseFloat(string(v), 64)
		if err != nil {
			return 0, false
		}
	default:
		return 0, false
	}
	return n, !math.IsNaN(n) && !math.IsInf(n, 0) && math.Trunc(n) == n && math.Abs(n) <= safeInteger
}
func validValue(value any, kind string) bool {
	switch kind {
	case "string":
		v, ok := value.(string)
		return ok && text(v) && utf8.RuneCountInString(v) > 0 && utf8.RuneCountInString(v) <= 256 && len(v) <= 1024
	case "boolean":
		_, ok := value.(bool)
		return ok
	case "integer":
		_, ok := number(value)
		return ok
	}
	return false
}

// Query contains parsed values. Page reparses its private raw input so changing
// exported presentation fields cannot bypass validation or schema restrictions.
type Query struct {
	Limit      int
	Offset     int
	Sort       string
	Descending bool
	Filters    map[string]any
	raw        string
	parsed     bool
}

func ParseQuery(raw string, schema *Schema) (Query, error) {
	invalid := func() (Query, error) { return Query{}, failure("INVALID_LIST_QUERY") }
	if !validSchema(schema) {
		return Query{}, failure("INVALID_LIST_SCHEMA")
	}
	if !text(raw) || strings.HasPrefix(raw, "?") || len(raw) > 2048 {
		return invalid()
	}
	pairs := []string{}
	if raw != "" {
		pairs = strings.Split(raw, "&")
	}
	if len(pairs) > 16 {
		return invalid()
	}
	decoded := map[string]string{}
	for _, pair := range pairs {
		key, value, ok := strings.Cut(pair, "=")
		if !ok || pair == "" {
			return invalid()
		}
		key, err := url.QueryUnescape(key)
		if err != nil || !text(key) {
			return invalid()
		}
		value, err = url.QueryUnescape(value)
		if err != nil || !text(value) {
			return invalid()
		}
		if _, duplicate := decoded[key]; duplicate {
			return invalid()
		}
		decoded[key] = value
	}
	query := Query{Limit: 20, Offset: 0, Sort: "id", Filters: map[string]any{}, raw: raw, parsed: true}
	for key, value := range decoded {
		switch key {
		case "limit", "offset":
			if !unsignedPattern.MatchString(value) || len(value) > 5 {
				return invalid()
			}
			n, err := strconv.Atoi(value)
			bound := 10000
			if key == "limit" {
				bound = 100
			}
			if err != nil || n > bound || (key == "limit" && n == 0) {
				return invalid()
			}
			if key == "limit" {
				query.Limit = n
			} else {
				query.Offset = n
			}
		case "sort":
			query.Descending = strings.HasPrefix(value, "-")
			query.Sort = strings.TrimPrefix(value, "-")
			if _, ok := schema.sortFields[query.Sort]; !ok {
				return invalid()
			}
		default:
			field := strings.TrimPrefix(key, "filter.")
			kind, ok := schema.filterFields[field]
			if !strings.HasPrefix(key, "filter.") || !ok {
				return invalid()
			}
			switch kind {
			case "integer":
				if !signedPattern.MatchString(value) || len(value) > 17 {
					return invalid()
				}
				n, err := strconv.ParseInt(value, 10, 64)
				if err != nil || n > safeInteger || n < -safeInteger {
					return invalid()
				}
				query.Filters[field] = n
			case "boolean":
				if value != "true" && value != "false" {
					return invalid()
				}
				query.Filters[field] = value == "true"
			case "string":
				if !validValue(value, kind) {
					return invalid()
				}
				query.Filters[field] = value
			}
		}
	}
	return query, nil
}

// Result is the JSON-compatible page envelope. NextOffset is nil at the end.
type Result struct {
	Items      []map[string]any `json:"items"`
	Total      int              `json:"total"`
	Limit      int              `json:"limit"`
	Offset     int              `json:"offset"`
	NextOffset *int             `json:"nextOffset"`
}

func compare(a, b any, kind string) int {
	if kind == "string" {
		return strings.Compare(a.(string), b.(string))
	}
	if kind == "boolean" {
		x, y := a.(bool), b.(bool)
		if x == y {
			return 0
		}
		if x {
			return 1
		}
		return -1
	}
	x, _ := number(a)
	y, _ := number(b)
	if x < y {
		return -1
	}
	if x > y {
		return 1
	}
	return 0
}
func Page(rows []map[string]any, query Query, schema *Schema) (Result, error) {
	if !validSchema(schema) {
		return Result{}, failure("INVALID_LIST_SCHEMA")
	}
	if !query.parsed {
		return Result{}, failure("INVALID_LIST_QUERY")
	}
	validated, err := ParseQuery(query.raw, schema)
	if err != nil {
		return Result{}, err
	}
	query = validated
	if len(rows) > 10000 {
		return Result{}, failure("INVALID_LIST_DATA")
	}
	ids := map[string]bool{}
	fields := map[string]string{query.Sort: schema.sortFields[query.Sort]}
	for field := range query.Filters {
		fields[field] = schema.filterFields[field]
	}
	for _, row := range rows {
		id, ok := row["id"].(string)
		if !ok || !idPattern.MatchString(id) || ids[id] {
			return Result{}, failure("INVALID_LIST_DATA")
		}
		ids[id] = true
		for field, kind := range fields {
			if !validValue(row[field], kind) {
				return Result{}, failure("INVALID_LIST_DATA")
			}
		}
	}
	selected := make([]map[string]any, 0, len(rows))
	for _, row := range rows {
		matched := true
		for field, value := range query.Filters {
			if compare(row[field], value, schema.filterFields[field]) != 0 {
				matched = false
				break
			}
		}
		if matched {
			selected = append(selected, row)
		}
	}
	sort.Slice(selected, func(i, j int) bool {
		result := compare(selected[i][query.Sort], selected[j][query.Sort], schema.sortFields[query.Sort])
		if result != 0 {
			if query.Descending {
				return result > 0
			}
			return result < 0
		}
		return selected[i]["id"].(string) < selected[j]["id"].(string)
	})
	result := Result{Items: []map[string]any{}, Total: len(selected), Limit: query.Limit, Offset: query.Offset}
	end := query.Offset + query.Limit
	if query.Offset < len(selected) {
		bounded := end
		if bounded > len(selected) {
			bounded = len(selected)
		}
		result.Items = selected[query.Offset:bounded]
	}
	if end < len(selected) {
		result.NextOffset = &end
	}
	return result, nil
}
