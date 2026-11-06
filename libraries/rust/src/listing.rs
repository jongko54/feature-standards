//! Strict offset-list-v1 parsing and bounded materialized-list pagination.
//! Callers must apply server authorization before passing rows to [`page`].
use serde_json::{Value, json};
use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;

const SAFE: f64 = 9_007_199_254_740_991.0;

/// Fixed contract failures. Raw query and data are never included.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ListingError {
    InvalidSchema,
    InvalidQuery,
    InvalidData,
}
impl ListingError {
    pub fn code(self) -> &'static str {
        match self {
            Self::InvalidSchema => "INVALID_LIST_SCHEMA",
            Self::InvalidQuery => "INVALID_LIST_QUERY",
            Self::InvalidData => "INVALID_LIST_DATA",
        }
    }
}
impl fmt::Display for ListingError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}
impl std::error::Error for ListingError {}

/// Immutable allowlist snapshot. Maps use string/integer/boolean type names.
#[derive(Debug, Clone)]
pub struct Schema {
    sort_fields: BTreeMap<String, String>,
    filter_fields: BTreeMap<String, String>,
}
impl Schema {
    pub fn new(
        sort_fields: BTreeMap<String, String>,
        filter_fields: BTreeMap<String, String>,
    ) -> Result<Self, ListingError> {
        for fields in [&sort_fields, &filter_fields] {
            if fields.len() > 16
                || fields.iter().any(|(field, kind)| {
                    !field_name(field) || !matches!(kind.as_str(), "string" | "integer" | "boolean")
                })
            {
                return Err(ListingError::InvalidSchema);
            }
        }
        if sort_fields.get("id").map(String::as_str) != Some("string")
            || filter_fields
                .iter()
                .any(|(field, kind)| sort_fields.get(field).is_some_and(|other| other != kind))
        {
            return Err(ListingError::InvalidSchema);
        }
        Ok(Self {
            sort_fields,
            filter_fields,
        })
    }
    pub fn sort_fields(&self) -> &BTreeMap<String, String> {
        &self.sort_fields
    }
    pub fn filter_fields(&self) -> &BTreeMap<String, String> {
        &self.filter_fields
    }
}

/// Values parsed from raw input. [`page`] reparses the private raw string.
#[derive(Debug, Clone)]
pub struct Query {
    pub limit: usize,
    pub offset: usize,
    pub sort: String,
    pub descending: bool,
    pub filters: BTreeMap<String, Value>,
    raw: String,
}
impl Query {
    pub fn raw(&self) -> &str {
        &self.raw
    }
}
fn field_name(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=32).contains(&bytes.len())
        && bytes[0].is_ascii_lowercase()
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || *byte == b'_')
}
fn identifier(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=64).contains(&bytes.len())
        && bytes[0].is_ascii_alphanumeric()
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(byte))
}
fn text(value: &str) -> bool {
    !value
        .chars()
        .any(|point| (point as u32) < 32 || point == '\u{7f}')
}
fn number(value: &Value) -> Option<f64> {
    value
        .as_f64()
        .filter(|number| number.is_finite() && number.fract() == 0.0 && number.abs() <= SAFE)
}
fn valid_value(value: &Value, kind: &str) -> bool {
    match kind {
        "string" => value.as_str().is_some_and(|string| {
            text(string) && (1..=256).contains(&string.chars().count()) && string.len() <= 1024
        }),
        "boolean" => value.is_boolean(),
        "integer" => number(value).is_some(),
        _ => false,
    }
}
fn unsigned(value: &str) -> bool {
    let bytes = value.as_bytes();
    value == "0"
        || (!bytes.is_empty()
            && (b'1'..=b'9').contains(&bytes[0])
            && bytes.iter().all(u8::is_ascii_digit))
}
fn signed(value: &str) -> bool {
    if let Some(rest) = value.strip_prefix('-') {
        rest != "0" && unsigned(rest)
    } else {
        unsigned(value)
    }
}
fn hex(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => Some(byte - b'0'),
        b'a'..=b'f' => Some(byte - b'a' + 10),
        b'A'..=b'F' => Some(byte - b'A' + 10),
        _ => None,
    }
}
fn decode(value: &str) -> Result<String, ListingError> {
    let mut output = Vec::with_capacity(value.len());
    let bytes = value.as_bytes();
    let mut index = 0;
    while index < bytes.len() {
        match bytes[index] {
            b'%' => {
                let high = bytes
                    .get(index + 1)
                    .and_then(|byte| hex(*byte))
                    .ok_or(ListingError::InvalidQuery)?;
                let low = bytes
                    .get(index + 2)
                    .and_then(|byte| hex(*byte))
                    .ok_or(ListingError::InvalidQuery)?;
                output.push(high * 16 + low);
                index += 3;
            }
            b'+' => {
                output.push(b' ');
                index += 1;
            }
            byte => {
                output.push(byte);
                index += 1;
            }
        }
    }
    let decoded = String::from_utf8(output).map_err(|_| ListingError::InvalidQuery)?;
    if !text(&decoded) {
        return Err(ListingError::InvalidQuery);
    }
    Ok(decoded)
}

pub fn parse_query(raw: &str, schema: &Schema) -> Result<Query, ListingError> {
    if !text(raw) || raw.starts_with('?') || raw.len() > 2048 {
        return Err(ListingError::InvalidQuery);
    }
    let pairs: Vec<&str> = if raw.is_empty() {
        Vec::new()
    } else {
        raw.split('&').collect()
    };
    if pairs.len() > 16 {
        return Err(ListingError::InvalidQuery);
    }
    let mut decoded = BTreeMap::new();
    for pair in pairs {
        let (key, value) = pair.split_once('=').ok_or(ListingError::InvalidQuery)?;
        let key = decode(key)?;
        let value = decode(value)?;
        if decoded.insert(key, value).is_some() {
            return Err(ListingError::InvalidQuery);
        }
    }
    let mut query = Query {
        limit: 20,
        offset: 0,
        sort: "id".into(),
        descending: false,
        filters: BTreeMap::new(),
        raw: raw.into(),
    };
    for (key, value) in decoded {
        match key.as_str() {
            "limit" | "offset" => {
                if !unsigned(&value) || value.len() > 5 {
                    return Err(ListingError::InvalidQuery);
                }
                let number = value
                    .parse::<usize>()
                    .map_err(|_| ListingError::InvalidQuery)?;
                let bound = if key == "limit" { 100 } else { 10000 };
                if number > bound || (key == "limit" && number == 0) {
                    return Err(ListingError::InvalidQuery);
                }
                if key == "limit" {
                    query.limit = number;
                } else {
                    query.offset = number;
                }
            }
            "sort" => {
                query.descending = value.starts_with('-');
                query.sort = value.strip_prefix('-').unwrap_or(&value).into();
                if !schema.sort_fields.contains_key(&query.sort) {
                    return Err(ListingError::InvalidQuery);
                }
            }
            _ => {
                let field = key
                    .strip_prefix("filter.")
                    .ok_or(ListingError::InvalidQuery)?;
                let kind = schema
                    .filter_fields
                    .get(field)
                    .ok_or(ListingError::InvalidQuery)?;
                let parsed = match kind.as_str() {
                    "integer" => {
                        if !signed(&value) || value.len() > 17 {
                            return Err(ListingError::InvalidQuery);
                        }
                        let number = value
                            .parse::<i64>()
                            .map_err(|_| ListingError::InvalidQuery)?;
                        if number.unsigned_abs() > 9_007_199_254_740_991 {
                            return Err(ListingError::InvalidQuery);
                        }
                        Value::from(number)
                    }
                    "boolean" => match value.as_str() {
                        "true" => Value::Bool(true),
                        "false" => Value::Bool(false),
                        _ => return Err(ListingError::InvalidQuery),
                    },
                    _ => {
                        let parsed = Value::String(value);
                        if !valid_value(&parsed, kind) {
                            return Err(ListingError::InvalidQuery);
                        }
                        parsed
                    }
                };
                query.filters.insert(field.into(), parsed);
            }
        }
    }
    Ok(query)
}
fn compare(left: &Value, right: &Value, kind: &str) -> Ordering {
    match kind {
        "string" => left.as_str().unwrap().cmp(right.as_str().unwrap()),
        "boolean" => left.as_bool().unwrap().cmp(&right.as_bool().unwrap()),
        _ => number(left)
            .unwrap()
            .partial_cmp(&number(right).unwrap())
            .unwrap(),
    }
}

/// Validate every referenced field before filtering, then order and slice.
/// Unreferenced fields are returned unchanged, without interpreting their data.
pub fn page(rows: &[Value], query: &Query, schema: &Schema) -> Result<Value, ListingError> {
    let query = parse_query(&query.raw, schema)?;
    if rows.len() > 10000 {
        return Err(ListingError::InvalidData);
    }
    let mut fields = BTreeMap::from([(
        query.sort.as_str(),
        schema.sort_fields[&query.sort].as_str(),
    )]);
    for field in query.filters.keys() {
        fields.insert(field, schema.filter_fields[field].as_str());
    }
    let mut ids = BTreeSet::new();
    for row in rows {
        let row = row.as_object().ok_or(ListingError::InvalidData)?;
        let id = row
            .get("id")
            .and_then(Value::as_str)
            .ok_or(ListingError::InvalidData)?;
        if !identifier(id) || !ids.insert(id) {
            return Err(ListingError::InvalidData);
        }
        for (field, kind) in &fields {
            if !row
                .get(*field)
                .is_some_and(|value| valid_value(value, kind))
            {
                return Err(ListingError::InvalidData);
            }
        }
    }
    let mut selected: Vec<&Value> = rows
        .iter()
        .filter(|row| {
            query.filters.iter().all(|(field, value)| {
                compare(&row[field], value, &schema.filter_fields[field]) == Ordering::Equal
            })
        })
        .collect();
    selected.sort_by(|left, right| {
        let primary = compare(
            &left[&query.sort],
            &right[&query.sort],
            &schema.sort_fields[&query.sort],
        );
        if primary != Ordering::Equal {
            if query.descending {
                primary.reverse()
            } else {
                primary
            }
        } else {
            left["id"]
                .as_str()
                .unwrap()
                .cmp(right["id"].as_str().unwrap())
        }
    });
    let total = selected.len();
    let end = query.offset + query.limit;
    let items: Vec<Value> = selected
        .into_iter()
        .skip(query.offset)
        .take(query.limit)
        .cloned()
        .collect();
    let next = if end < total { Some(end) } else { None };
    Ok(
        json!({"items":items,"total":total,"limit":query.limit,"offset":query.offset,"nextOffset":next}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    fn schema() -> Schema {
        Schema::new(
            BTreeMap::from([
                ("id".into(), "string".into()),
                ("name".into(), "string".into()),
                ("count".into(), "integer".into()),
                ("active".into(), "boolean".into()),
            ]),
            BTreeMap::from([
                ("name".into(), "string".into()),
                ("count".into(), "integer".into()),
                ("active".into(), "boolean".into()),
            ]),
        )
        .unwrap()
    }
    fn fixture_schema(raw: &Value) -> Result<Schema, ListingError> {
        fn fields(value: &Value) -> BTreeMap<String, String> {
            value
                .as_object()
                .unwrap()
                .iter()
                .map(|(field, kind)| (field.clone(), kind.as_str().unwrap().into()))
                .collect()
        }
        Schema::new(fields(&raw["sortFields"]), fields(&raw["filterFields"]))
    }
    #[test]
    fn shared_vectors() {
        let fixture: Value =
            serde_json::from_str(include_str!("../../../features/listing/scenarios.json")).unwrap();
        for vector in fixture["cases"].as_array().unwrap() {
            let result = fixture_schema(&vector["schema"]).and_then(|selected| {
                parse_query(vector["query"].as_str().unwrap(), &selected)
                    .and_then(|query| page(vector["items"].as_array().unwrap(), &query, &selected))
            });
            if let Some(error) = vector["expected"]["error"].as_str() {
                assert_eq!(result.unwrap_err().code(), error, "{}", vector["id"]);
            } else {
                assert_eq!(result.unwrap(), vector["expected"], "{}", vector["id"]);
            }
        }
    }
    #[test]
    fn stable_ties_scalar_order_and_reparsed_query() {
        let selected = schema();
        let rows = vec![
            json!({"id":"b","count":2}),
            json!({"id":"a","count":2}),
            json!({"id":"c","count":1}),
        ];
        let mut query = parse_query("sort=-count&limit=1", &selected).unwrap();
        query.limit = 10000;
        query.filters.insert("count".into(), json!(false));
        let result = page(&rows, &query, &selected).unwrap();
        assert_eq!(result["items"][0]["id"], "a");
        assert_eq!(result["limit"], 1);
        assert_eq!(result["nextOffset"], 1);
        assert_eq!(rows[0]["id"], "b");
        let rows = vec![
            json!({"id":"a","name":"\u{10000}"}),
            json!({"id":"b","name":"\u{e000}"}),
        ];
        assert_eq!(
            page(
                &rows,
                &parse_query("sort=name", &selected).unwrap(),
                &selected
            )
            .unwrap()["items"][0]["id"],
            "b"
        );
    }
    #[test]
    fn native_bounds_and_validation_before_filtering() {
        let selected = schema();
        for raw in [
            "sort=id\n",
            "filter.name=%ED%A0%80",
            "filter.name=%FF",
            "filter.count=-0",
        ] {
            assert_eq!(
                parse_query(raw, &selected).unwrap_err().to_string(),
                "INVALID_LIST_QUERY"
            );
        }
        let rows = vec![json!({"id":"a","active":false,"count":1.5})];
        assert_eq!(
            page(
                &rows,
                &parse_query("sort=count&filter.active=true", &selected).unwrap(),
                &selected
            )
            .unwrap_err(),
            ListingError::InvalidData
        );
        let rows = vec![json!({"id":"a"}); 10001];
        assert_eq!(
            page(&rows, &parse_query("", &selected).unwrap(), &selected).unwrap_err(),
            ListingError::InvalidData
        );
    }
}
