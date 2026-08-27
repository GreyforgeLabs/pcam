use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

pub const CUSTOM_ORDERED_I64_FOLD_ID: &str = "greyforge.effect.ordered-i64-fold.v1";
pub const CUSTOM_ORDERED_I64_FOLD_HASH: &str =
    "6316bc089aaf70e9db41fc7556475b8213181b68da9eddd980b8d1971f632a35";
pub const CUSTOM_ORDERED_I64_FOLD_SEMANTICS: &str = "pcam.runtime.custom.ordered-i64-fold.v1";
pub const CUSTOM_ORDERING: &str = "pcam.order.canonical-effect.v1";
pub const CUSTOM_OVERFLOW: &str = "pcam.overflow.checked-i64.v1";
pub const CUSTOM_SAVE_RESTORE: &str = "pcam.save.stateless.v1";
pub const CUSTOM_ROLLBACK: &str = "pcam.rollback.snapshot-restore.v1";
const CUSTOM_ORDERED_I64_FOLD_SOURCE: &[u8] =
    include_bytes!("../../../reference/effects/ordered-i64-fold-v1.json");

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EffectError {
    IntegerOverflow,
    UnknownEffect,
    InvalidRegistration,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct CustomEffectRegistration {
    pub effect_type: String,
    pub implementation_id: String,
    pub implementation_hash: String,
    pub implementation_path: String,
    pub payload_schema: Value,
    pub determinism_vectors: Vec<String>,
    pub reducer: String,
    pub runtime_semantics_id: String,
    pub ordering_id: String,
    pub overflow_behavior_id: String,
    pub save_restore_id: String,
    pub rollback_behavior_id: String,
}

impl CustomEffectRegistration {
    pub fn validate(&self) -> Result<(), EffectError> {
        let actual_hash = Sha256::digest(CUSTOM_ORDERED_I64_FOLD_SOURCE)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let unique_vectors = self.determinism_vectors.iter().collect::<BTreeSet<_>>();
        if !valid_identifier(&self.effect_type)
            || self.implementation_id != CUSTOM_ORDERED_I64_FOLD_ID
            || self.implementation_hash != CUSTOM_ORDERED_I64_FOLD_HASH
            || self.implementation_hash != actual_hash
            || self.implementation_path != "reference/effects/ordered-i64-fold-v1.json"
            || self.payload_schema != json!({"type": "integer"})
            || self.determinism_vectors.is_empty()
            || unique_vectors.len() != self.determinism_vectors.len()
            || self
                .determinism_vectors
                .iter()
                .any(|digest| !valid_digest(digest))
            || self.reducer != "CUSTOM_DETERMINISTIC"
            || self.runtime_semantics_id != CUSTOM_ORDERED_I64_FOLD_SEMANTICS
            || self.ordering_id != CUSTOM_ORDERING
            || self.overflow_behavior_id != CUSTOM_OVERFLOW
            || self.save_restore_id != CUSTOM_SAVE_RESTORE
            || self.rollback_behavior_id != CUSTOM_ROLLBACK
        {
            return Err(EffectError::InvalidRegistration);
        }
        Ok(())
    }

    pub fn identity_record(&self) -> Value {
        let mut vectors = self.determinism_vectors.clone();
        vectors.sort();
        json!({
            "determinism_vectors": vectors,
            "effect_type": self.effect_type,
            "implementation_hash": self.implementation_hash,
            "implementation_id": self.implementation_id,
            "ordering_id": self.ordering_id,
            "overflow_behavior_id": self.overflow_behavior_id,
            "payload_schema": self.payload_schema,
            "reducer": self.reducer,
            "rollback_behavior_id": self.rollback_behavior_id,
            "runtime_semantics_id": self.runtime_semantics_id,
            "save_restore_id": self.save_restore_id,
        })
    }
}

pub fn custom_registry(
    registrations: Vec<CustomEffectRegistration>,
) -> Result<BTreeMap<String, CustomEffectRegistration>, EffectError> {
    let mut registry = BTreeMap::new();
    for registration in registrations {
        registration.validate()?;
        if registry
            .insert(registration.effect_type.clone(), registration)
            .is_some()
        {
            return Err(EffectError::InvalidRegistration);
        }
    }
    Ok(registry)
}

pub fn custom_registry_identity(registry: &BTreeMap<String, CustomEffectRegistration>) -> Value {
    Value::Array(
        registry
            .values()
            .map(CustomEffectRegistration::identity_record)
            .collect(),
    )
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct EffectEnvelope {
    pub effect_id: String,
    pub effect_type: String,
    pub effect_class: String,
    pub source_entity_id: u64,
    pub target_entity_id: u64,
    pub source_action_instance_id: u64,
    pub origin_tick: u64,
    pub priority: i64,
    pub payload: Value,
    pub reducer: String,
    #[serde(default = "enabled")]
    pub authoritative: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ReducedEffect {
    pub target_entity_id: u64,
    pub effect_type: String,
    pub reducer: String,
    pub value: Value,
    pub source_effect_ids: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RejectedEffect {
    pub effect_id: String,
    pub reason: String,
}

pub fn canonical_effects(effects: &[EffectEnvelope]) -> Result<Vec<EffectEnvelope>, EffectError> {
    let mut identifiers = BTreeSet::new();
    if effects
        .iter()
        .any(|effect| !identifiers.insert(effect.effect_id.as_str()))
    {
        return Err(EffectError::UnknownEffect);
    }
    let mut ordered = effects.to_vec();
    ordered.sort_by(|left, right| {
        left.target_entity_id
            .cmp(&right.target_entity_id)
            .then_with(|| {
                left.effect_type
                    .as_bytes()
                    .cmp(right.effect_type.as_bytes())
            })
            .then_with(|| right.priority.cmp(&left.priority))
            .then_with(|| left.source_entity_id.cmp(&right.source_entity_id))
            .then_with(|| {
                left.source_action_instance_id
                    .cmp(&right.source_action_instance_id)
            })
            .then_with(|| left.effect_id.as_bytes().cmp(right.effect_id.as_bytes()))
    });
    Ok(ordered)
}

pub fn reduce_effects(
    effects: &[EffectEnvelope],
) -> Result<(Vec<ReducedEffect>, Vec<RejectedEffect>), EffectError> {
    reduce_effects_with_registry(effects, &BTreeMap::new())
}

pub fn reduce_effects_with_registry(
    effects: &[EffectEnvelope],
    custom_registry: &BTreeMap<String, CustomEffectRegistration>,
) -> Result<(Vec<ReducedEffect>, Vec<RejectedEffect>), EffectError> {
    let mut groups: BTreeMap<(u64, String), Vec<EffectEnvelope>> = BTreeMap::new();
    for effect in canonical_effects(effects)? {
        groups
            .entry((effect.target_entity_id, effect.effect_type.clone()))
            .or_default()
            .push(effect);
    }
    let mut reduced = Vec::new();
    let mut rejected = Vec::new();
    for ((target_entity_id, effect_type), group) in groups {
        let reducers: BTreeSet<&str> = group.iter().map(|effect| effect.reducer.as_str()).collect();
        if reducers.len() != 1 {
            return Err(EffectError::UnknownEffect);
        }
        let reducer = group[0].reducer.clone();
        let (value, group_rejected) =
            reduce_group(&effect_type, &reducer, &group, custom_registry)?;
        reduced.push(ReducedEffect {
            target_entity_id,
            effect_type,
            reducer,
            value,
            source_effect_ids: group
                .iter()
                .map(|effect| effect.effect_id.clone())
                .collect(),
        });
        rejected.extend(group_rejected);
    }
    Ok((reduced, rejected))
}

fn reduce_group(
    effect_type: &str,
    reducer: &str,
    effects: &[EffectEnvelope],
    custom_registry: &BTreeMap<String, CustomEffectRegistration>,
) -> Result<(Value, Vec<RejectedEffect>), EffectError> {
    let payloads: Vec<Value> = effects
        .iter()
        .map(|effect| effect.payload.clone())
        .collect();
    let value = match reducer {
        "SUM" => {
            let mut total = 0_i64;
            for payload in &payloads {
                total = total
                    .checked_add(integer_payload(payload)?)
                    .ok_or(EffectError::IntegerOverflow)?;
            }
            Value::from(total)
        }
        "MIN" => Value::from(
            payloads
                .iter()
                .map(integer_payload)
                .collect::<Result<Vec<_>, _>>()?
                .into_iter()
                .min()
                .ok_or(EffectError::UnknownEffect)?,
        ),
        "MAX" => Value::from(
            payloads
                .iter()
                .map(integer_payload)
                .collect::<Result<Vec<_>, _>>()?
                .into_iter()
                .max()
                .ok_or(EffectError::UnknownEffect)?,
        ),
        "SET_UNION" => {
            let mut union = BTreeSet::new();
            for payload in &payloads {
                let values = payload.as_array().ok_or(EffectError::UnknownEffect)?;
                for value in values {
                    union.insert(value.as_str().ok_or(EffectError::UnknownEffect)?.to_owned());
                }
            }
            Value::Array(union.into_iter().map(Value::String).collect())
        }
        "ORDERED" => Value::Array(payloads),
        "FIRST" => payloads
            .first()
            .cloned()
            .ok_or(EffectError::UnknownEffect)?,
        "LAST" => payloads.last().cloned().ok_or(EffectError::UnknownEffect)?,
        "EXCLUSIVE" => payloads
            .first()
            .cloned()
            .ok_or(EffectError::UnknownEffect)?,
        "CUSTOM_DETERMINISTIC" => {
            let registration = custom_registry
                .get(effect_type)
                .ok_or(EffectError::UnknownEffect)?;
            registration.validate()?;
            let mut accumulator = 0_i64;
            for payload in &payloads {
                let payload = integer_payload(payload)?;
                accumulator = accumulator
                    .checked_mul(10)
                    .and_then(|value| value.checked_add(payload))
                    .ok_or(EffectError::IntegerOverflow)?;
            }
            Value::from(accumulator)
        }
        _ => return Err(EffectError::UnknownEffect),
    };
    let rejected = if reducer == "EXCLUSIVE" {
        effects[1..]
            .iter()
            .map(|effect| RejectedEffect {
                effect_id: effect.effect_id.clone(),
                reason: "EXCLUSIVE_EFFECT_LOST".to_owned(),
            })
            .collect()
    } else {
        Vec::new()
    };
    Ok((value, rejected))
}

fn integer_payload(value: &Value) -> Result<i64, EffectError> {
    value.as_i64().ok_or(EffectError::UnknownEffect)
}

fn enabled() -> bool {
    true
}

fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .as_bytes()
            .iter()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(byte))
}

fn valid_identifier(value: &str) -> bool {
    let bytes = value.as_bytes();
    matches!(bytes.first(), Some(byte) if byte.is_ascii_alphabetic())
        && bytes.len() <= 128
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'.' | b':' | b'-'))
}
