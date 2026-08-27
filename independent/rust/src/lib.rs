use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use unicode_normalization::UnicodeNormalization;

pub mod action;
pub mod expression;
pub mod extension;
pub mod numeric;
pub mod rng;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CanonicalError {
    FloatingPoint,
    NormalizedKeyCollision(String),
    UnsupportedNumber,
    Json(String),
}

impl std::fmt::Display for CanonicalError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::FloatingPoint => write!(formatter, "PCAM-CJ1 forbids floating-point numbers"),
            Self::NormalizedKeyCollision(key) => {
                write!(
                    formatter,
                    "object key collides after NFC normalization: {key}"
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
    let value: Value =
        serde_json::from_slice(source).map_err(|error| CanonicalError::Json(error.to_string()))?;
    canonicalize(&value)
}

pub fn canonical_hash(value: &Value) -> Result<String, CanonicalError> {
    Ok(hex_sha256(&canonicalize(value)?))
}

pub fn canonical_hash_json(source: &[u8]) -> Result<String, CanonicalError> {
    Ok(hex_sha256(&canonicalize_json(source)?))
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
