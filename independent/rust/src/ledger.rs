use crate::{CanonicalError, canonical_hash};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::BTreeMap;

#[derive(Debug)]
pub enum LedgerError {
    Canonical(CanonicalError),
    InvalidPolicy,
    InvalidReceiptCondition,
    InvalidState,
}

impl From<CanonicalError> for LedgerError {
    fn from(error: CanonicalError) -> Self {
        Self::Canonical(error)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct HitPolicy {
    pub kind: String,
    pub receipt_on: String,
    #[serde(default)]
    pub cooldown_ticks: Option<u64>,
    #[serde(default)]
    pub predicate_id: Option<String>,
}

impl HitPolicy {
    pub fn validate(&self) -> Result<(), LedgerError> {
        match self.kind.as_str() {
            "UNBOUNDED"
            | "ONCE_PER_ACTION_INSTANCE"
            | "ONCE_PER_CYCLE"
            | "ONCE_PER_CONTACT_PARTITION" => {}
            "ONCE_PER_PREDICATE_ACTIVATION" => {
                if self.predicate_id.as_deref().is_none_or(str::is_empty) {
                    return Err(LedgerError::InvalidPolicy);
                }
            }
            "COOLDOWN_TICKS" => {
                if self.cooldown_ticks.is_none_or(|ticks| ticks == 0) {
                    return Err(LedgerError::InvalidPolicy);
                }
            }
            _ => return Err(LedgerError::InvalidPolicy),
        }
        if !matches!(
            self.receipt_on.as_str(),
            "ON_CONTACT" | "ON_ACCEPT" | "ON_IMPACT"
        ) {
            return Err(LedgerError::InvalidReceiptCondition);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LedgerContext {
    pub tick: u64,
    pub source_action_instance_id: u64,
    pub offense_fact_id: String,
    pub target_entity_id: u64,
    pub cycle: u64,
    pub predicate_entry_serials: BTreeMap<String, u64>,
    pub contact_partition: String,
}

pub fn ledger_key(
    policy: &HitPolicy,
    context: &LedgerContext,
) -> Result<Option<String>, LedgerError> {
    policy.validate()?;
    if policy.kind == "UNBOUNDED" {
        return Ok(None);
    }
    let mut fields = serde_json::Map::from_iter([
        ("fact".to_owned(), json!(context.offense_fact_id)),
        (
            "instance".to_owned(),
            json!(context.source_action_instance_id),
        ),
        ("policy".to_owned(), json!(policy.kind)),
        ("target".to_owned(), json!(context.target_entity_id)),
    ]);
    match policy.kind.as_str() {
        "ONCE_PER_CYCLE" => {
            fields.insert("cycle".to_owned(), json!(context.cycle));
        }
        "ONCE_PER_PREDICATE_ACTIVATION" => {
            let predicate = policy
                .predicate_id
                .as_ref()
                .ok_or(LedgerError::InvalidPolicy)?;
            fields.insert("predicate".to_owned(), json!(predicate));
            fields.insert(
                "predicate_entry_serial".to_owned(),
                json!(
                    context
                        .predicate_entry_serials
                        .get(predicate)
                        .copied()
                        .unwrap_or(0)
                ),
            );
        }
        "ONCE_PER_CONTACT_PARTITION" => {
            fields.insert(
                "contact_partition".to_owned(),
                json!(context.contact_partition),
            );
        }
        _ => {}
    }
    Ok(Some(canonical_hash(&Value::Object(fields))?))
}

pub fn is_eligible(
    ledger: &BTreeMap<String, Value>,
    policy: &HitPolicy,
    context: &LedgerContext,
) -> Result<bool, LedgerError> {
    let Some(key) = ledger_key(policy, context)? else {
        return Ok(true);
    };
    let Some(existing) = ledger.get(&key) else {
        return Ok(true);
    };
    if policy.kind != "COOLDOWN_TICKS" {
        return Ok(false);
    }
    let origin_tick = existing
        .get("origin_tick")
        .and_then(Value::as_u64)
        .ok_or(LedgerError::InvalidState)?;
    let elapsed = context
        .tick
        .checked_sub(origin_tick)
        .ok_or(LedgerError::InvalidState)?;
    Ok(elapsed >= policy.cooldown_ticks.ok_or(LedgerError::InvalidPolicy)?)
}

pub fn receipt_required(
    condition: &str,
    accepted_after_routing: bool,
    authoritative_impact_materialized: bool,
) -> Result<bool, LedgerError> {
    match condition {
        "ON_CONTACT" => Ok(true),
        "ON_ACCEPT" => Ok(accepted_after_routing),
        "ON_IMPACT" => Ok(authoritative_impact_materialized),
        _ => Err(LedgerError::InvalidReceiptCondition),
    }
}

pub fn write_receipt(
    ledger: &mut BTreeMap<String, Value>,
    policy: &HitPolicy,
    context: &LedgerContext,
    candidate_id: &str,
) -> Result<bool, LedgerError> {
    let Some(key) = ledger_key(policy, context)? else {
        return Ok(false);
    };
    ledger.insert(
        key,
        json!({
            "candidate_id": candidate_id,
            "condition": policy.receipt_on,
            "origin_tick": context.tick,
        }),
    );
    Ok(true)
}
