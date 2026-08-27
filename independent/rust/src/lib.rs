use serde::Deserialize;
use serde::de::{MapAccess, SeqAccess, Visitor};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use unicode_normalization::UnicodeNormalization;

pub mod action;
pub mod arbitration;
pub mod effects;
pub mod events;
pub mod expression;
pub mod extension;
pub mod faults;
pub mod freezes;
pub mod interactions;
pub mod ledger;
pub mod numeric;
pub mod rng;
pub mod simulation;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CanonicalError {
    FloatingPoint,
    NegativeZero,
    NormalizedKeyCollision(String),
    NormalizedSetCollision,
    NormalizedLogicalKeyCollision,
    UnsupportedNumber,
    Json(String),
}

impl std::fmt::Display for CanonicalError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::FloatingPoint => write!(formatter, "PCAM-CJ1 forbids floating-point numbers"),
            Self::NegativeZero => write!(formatter, "PCAM-CJ1 forbids negative zero"),
            Self::NormalizedKeyCollision(key) => {
                write!(
                    formatter,
                    "object key collides after NFC normalization: {key}"
                )
            }
            Self::NormalizedSetCollision => {
                write!(
                    formatter,
                    "set entries collide after canonical normalization"
                )
            }
            Self::NormalizedLogicalKeyCollision => {
                write!(
                    formatter,
                    "logical map keys collide after canonical normalization"
                )
            }
            Self::UnsupportedNumber => {
                write!(formatter, "number is outside the supported integer domain")
            }
            Self::Json(message) => write!(formatter, "JSON error: {message}"),
        }
    }
}

impl std::error::Error for CanonicalError {}

pub fn canonicalize(value: &Value) -> Result<Vec<u8>, CanonicalError> {
    let normalized = normalize(value)?;
    let mut output = String::new();
    encode(&normalized, &mut output)?;
    Ok(output.into_bytes())
}

pub fn canonicalize_json(source: &[u8]) -> Result<Vec<u8>, CanonicalError> {
    validate_number_tokens(source)?;
    if source.starts_with(&[0xef, 0xbb, 0xbf]) {
        return Err(CanonicalError::Json(
            "UTF-8 BOM is not canonical JSON input".to_string(),
        ));
    }
    let mut deserializer = serde_json::Deserializer::from_slice(source);
    let parsed = ParsedValue::deserialize(&mut deserializer).map_err(translate_json_error)?;
    deserializer.end().map_err(translate_json_error)?;
    canonicalize(&parsed.0)
}

pub fn canonical_hash(value: &Value) -> Result<String, CanonicalError> {
    Ok(hex_sha256(&canonicalize(value)?))
}

pub fn canonical_hash_json(source: &[u8]) -> Result<String, CanonicalError> {
    Ok(hex_sha256(&canonicalize_json(source)?))
}

pub fn canonicalize_set(values: &[Value]) -> Result<Vec<u8>, CanonicalError> {
    let mut encoded = values
        .iter()
        .map(canonicalize)
        .collect::<Result<Vec<_>, _>>()?;
    encoded.sort();
    if encoded.windows(2).any(|window| window[0] == window[1]) {
        return Err(CanonicalError::NormalizedSetCollision);
    }
    Ok(join_entries(b'[', b']', &encoded))
}

pub fn canonicalize_logical_map(entries: &[(Value, Value)]) -> Result<Vec<u8>, CanonicalError> {
    let mut encoded = entries
        .iter()
        .map(|(key, value)| Ok((canonicalize(key)?, canonicalize(value)?)))
        .collect::<Result<Vec<_>, CanonicalError>>()?;
    encoded.sort_by(|left, right| left.0.cmp(&right.0));
    if encoded.windows(2).any(|window| window[0].0 == window[1].0) {
        return Err(CanonicalError::NormalizedLogicalKeyCollision);
    }
    let pairs = encoded
        .into_iter()
        .map(|(key, value)| {
            let mut pair = Vec::with_capacity(key.len() + value.len() + 3);
            pair.push(b'[');
            pair.extend(key);
            pair.push(b',');
            pair.extend(value);
            pair.push(b']');
            pair
        })
        .collect::<Vec<_>>();
    Ok(join_entries(b'[', b']', &pairs))
}

const KEY_COLLISION_MARKER: &str = "PCAM_NORMALIZED_KEY_COLLISION:";

struct ParsedValue(Value);

impl<'de> Deserialize<'de> for ParsedValue {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        deserializer.deserialize_any(ParsedValueVisitor)
    }
}

struct ParsedValueVisitor;

impl<'de> Visitor<'de> for ParsedValueVisitor {
    type Value = ParsedValue;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a PCAM-CJ1 JSON value")
    }

    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(ParsedValue(Value::Null))
    }

    fn visit_none<E>(self) -> Result<Self::Value, E> {
        Ok(ParsedValue(Value::Null))
    }

    fn visit_bool<E>(self, value: bool) -> Result<Self::Value, E> {
        Ok(ParsedValue(Value::Bool(value)))
    }

    fn visit_i64<E>(self, value: i64) -> Result<Self::Value, E> {
        Ok(ParsedValue(Value::Number(value.into())))
    }

    fn visit_u64<E>(self, value: u64) -> Result<Self::Value, E> {
        Ok(ParsedValue(Value::Number(value.into())))
    }

    fn visit_f64<E>(self, value: f64) -> Result<Self::Value, E>
    where
        E: serde::de::Error,
    {
        let number = serde_json::Number::from_f64(value)
            .ok_or_else(|| E::custom("non-finite floating-point number"))?;
        Ok(ParsedValue(Value::Number(number)))
    }

    fn visit_str<E>(self, value: &str) -> Result<Self::Value, E> {
        Ok(ParsedValue(Value::String(value.to_string())))
    }

    fn visit_string<E>(self, value: String) -> Result<Self::Value, E> {
        Ok(ParsedValue(Value::String(value)))
    }

    fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        let mut values = Vec::new();
        while let Some(value) = sequence.next_element::<ParsedValue>()? {
            values.push(value.0);
        }
        Ok(ParsedValue(Value::Array(values)))
    }

    fn visit_map<A>(self, mut map: A) -> Result<Self::Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        let mut values = serde_json::Map::new();
        let mut normalized_keys = BTreeSet::new();
        while let Some(key) = map.next_key::<String>()? {
            let normalized: String = key.nfc().collect();
            if !normalized_keys.insert(normalized.clone()) {
                return Err(serde::de::Error::custom(format!(
                    "{KEY_COLLISION_MARKER}{normalized}"
                )));
            }
            let value = map.next_value::<ParsedValue>()?;
            values.insert(key, value.0);
        }
        Ok(ParsedValue(Value::Object(values)))
    }
}

fn translate_json_error(error: serde_json::Error) -> CanonicalError {
    let message = error.to_string();
    if let Some(marker) = message.find(KEY_COLLISION_MARKER) {
        let key = message[marker + KEY_COLLISION_MARKER.len()..]
            .split(" at line")
            .next()
            .unwrap_or_default()
            .to_string();
        CanonicalError::NormalizedKeyCollision(key)
    } else {
        CanonicalError::Json(message)
    }
}

fn validate_number_tokens(source: &[u8]) -> Result<(), CanonicalError> {
    let mut index = 0;
    let mut in_string = false;
    let mut escaped = false;
    while index < source.len() {
        let byte = source[index];
        if in_string {
            if escaped {
                escaped = false;
            } else if byte == b'\\' {
                escaped = true;
            } else if byte == b'"' {
                in_string = false;
            }
        } else if byte == b'"' {
            in_string = true;
        } else if byte == b'-' || byte.is_ascii_digit() {
            let start = index;
            index += 1;
            while source.get(index).is_some_and(|item| {
                item.is_ascii_digit() || matches!(item, b'+' | b'-' | b'.' | b'e' | b'E')
            }) {
                index += 1;
            }
            let token = &source[start..index];
            let integer = !token.iter().any(|item| matches!(item, b'.' | b'e' | b'E'));
            let digits = token.strip_prefix(b"-").unwrap_or(token);
            if integer && !digits.is_empty() && digits.iter().all(u8::is_ascii_digit) {
                if token == b"-0" {
                    return Err(CanonicalError::NegativeZero);
                }
                let text = std::str::from_utf8(token)
                    .map_err(|error| CanonicalError::Json(error.to_string()))?;
                let in_domain = if token.starts_with(b"-") {
                    text.parse::<i64>().is_ok()
                } else {
                    text.parse::<u64>().is_ok()
                };
                if !in_domain {
                    return Err(CanonicalError::UnsupportedNumber);
                }
            }
            continue;
        }
        index += 1;
    }
    Ok(())
}

fn join_entries(open: u8, close: u8, entries: &[Vec<u8>]) -> Vec<u8> {
    let size = entries.iter().map(Vec::len).sum::<usize>() + entries.len().saturating_sub(1) + 2;
    let mut output = Vec::with_capacity(size);
    output.push(open);
    for (index, entry) in entries.iter().enumerate() {
        if index > 0 {
            output.push(b',');
        }
        output.extend(entry);
    }
    output.push(close);
    output
}

fn normalize(value: &Value) -> Result<Value, CanonicalError> {
    match value {
        Value::Null | Value::Bool(_) => Ok(value.clone()),
        Value::Number(number) => {
            if number.is_i64() || number.is_u64() {
                Ok(value.clone())
            } else if number.is_f64() {
                Err(CanonicalError::FloatingPoint)
            } else {
                Err(CanonicalError::UnsupportedNumber)
            }
        }
        Value::String(text) => Ok(Value::String(text.nfc().collect())),
        Value::Array(items) => items
            .iter()
            .map(normalize)
            .collect::<Result<Vec<_>, _>>()
            .map(Value::Array),
        Value::Object(items) => {
            let mut normalized = BTreeMap::new();
            for (key, item) in items {
                let normalized_key: String = key.nfc().collect();
                if normalized.contains_key(&normalized_key) {
                    return Err(CanonicalError::NormalizedKeyCollision(normalized_key));
                }
                normalized.insert(normalized_key, normalize(item)?);
            }
            let object = normalized.into_iter().collect();
            Ok(Value::Object(object))
        }
    }
}

fn encode(value: &Value, output: &mut String) -> Result<(), CanonicalError> {
    match value {
        Value::Null => output.push_str("null"),
        Value::Bool(boolean) => output.push_str(if *boolean { "true" } else { "false" }),
        Value::Number(number) => {
            if !number.is_i64() && !number.is_u64() {
                return Err(CanonicalError::FloatingPoint);
            }
            output.push_str(&number.to_string());
        }
        Value::String(text) => output.push_str(
            &serde_json::to_string(text)
                .map_err(|error| CanonicalError::Json(error.to_string()))?,
        ),
        Value::Array(items) => {
            output.push('[');
            for (index, item) in items.iter().enumerate() {
                if index > 0 {
                    output.push(',');
                }
                encode(item, output)?;
            }
            output.push(']');
        }
        Value::Object(items) => {
            output.push('{');
            let mut entries: Vec<_> = items.iter().collect();
            entries.sort_by(|left, right| left.0.as_bytes().cmp(right.0.as_bytes()));
            for (index, (key, item)) in entries.into_iter().enumerate() {
                if index > 0 {
                    output.push(',');
                }
                output.push_str(
                    &serde_json::to_string(key)
                        .map_err(|error| CanonicalError::Json(error.to_string()))?,
                );
                output.push(':');
                encode(item, output)?;
            }
            output.push('}');
        }
    }
    Ok(())
}

fn hex_sha256(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}
