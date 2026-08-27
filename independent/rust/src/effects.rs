use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EffectError {
    IntegerOverflow,
    UnknownEffect,
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
        let (value, group_rejected) = reduce_group(&reducer, &group)?;
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
    reducer: &str,
    effects: &[EffectEnvelope],
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
        "CUSTOM_DETERMINISTIC" | _ => return Err(EffectError::UnknownEffect),
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
