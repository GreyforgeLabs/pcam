use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ArbitrationError {
    IntegerOverflow,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct Claim {
    pub kind: String,
    pub key: String,
    #[serde(default = "one")]
    pub amount: u64,
    pub owner_id: Option<u64>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct Intent {
    pub intent_kind: String,
    pub intent_priority: i64,
    pub owner_entity_id: u64,
    pub source_action_instance_id: u64,
    pub transition_id: String,
    pub input_sequence: u64,
    pub input_id: String,
    #[serde(default)]
    pub claims: Vec<Claim>,
    #[serde(default)]
    pub releases: Vec<Claim>,
    #[serde(default)]
    pub operations: Vec<Value>,
    #[serde(default = "default_group")]
    pub atomic_group_id: String,
}

impl Intent {
    pub fn identity(&self) -> String {
        format!(
            "{}:{}:{}:{}:{}",
            self.owner_entity_id,
            self.source_action_instance_id,
            self.transition_id,
            self.input_sequence,
            self.input_id
        )
    }
}

pub type CapacityKey = (String, u64, String);

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct ArbitrationState {
    pub resource_banks: BTreeMap<u64, BTreeMap<String, u64>>,
    pub capacities: BTreeMap<CapacityKey, u64>,
    pub usages: BTreeMap<CapacityKey, u64>,
    pub exclusive_keys: BTreeSet<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IntentDecision {
    pub intent: Intent,
    pub accepted: bool,
    pub reason: String,
}

pub fn canonical_intents(intents: &[Intent]) -> Vec<Intent> {
    let mut ordered = intents.to_vec();
    ordered.sort_by(|left, right| {
        right
            .intent_priority
            .cmp(&left.intent_priority)
            .then_with(|| left.owner_entity_id.cmp(&right.owner_entity_id))
            .then_with(|| {
                left.source_action_instance_id
                    .cmp(&right.source_action_instance_id)
            })
            .then_with(|| {
                left.transition_id
                    .as_bytes()
                    .cmp(right.transition_id.as_bytes())
            })
            .then_with(|| left.input_sequence.cmp(&right.input_sequence))
            .then_with(|| left.input_id.as_bytes().cmp(right.input_id.as_bytes()))
    });
    ordered
}

pub fn arbitrate(
    intents: &[Intent],
    state: &ArbitrationState,
) -> Result<(ArbitrationState, Vec<IntentDecision>), ArbitrationError> {
    let mut work = state.clone();
    let mut decisions = Vec::new();
    for intent in canonical_intents(intents) {
        let claims = aggregate(&intent.claims)?;
        let releases = aggregate(&intent.releases)?;
        if let Some(reason) = first_failure(&intent, &claims, &releases, &work)? {
            decisions.push(IntentDecision {
                intent,
                accepted: false,
                reason,
            });
            continue;
        }
        reserve(&intent, &claims, &releases, &mut work)?;
        decisions.push(IntentDecision {
            intent,
            accepted: true,
            reason: "ACCEPTED".to_owned(),
        });
    }
    Ok((work, decisions))
}

pub fn allocate_action_instance_ids(
    decisions: &[IntentDecision],
    next_action_instance_id: u64,
) -> Result<(BTreeMap<String, u64>, u64), ArbitrationError> {
    let mut next = next_action_instance_id;
    let mut allocated = BTreeMap::new();
    for decision in decisions {
        if !decision.accepted {
            continue;
        }
        let starts = decision
            .intent
            .operations
            .iter()
            .filter(|operation| operation.get("start_action").is_some())
            .count() as u64;
        if starts > 0 {
            allocated.insert(decision.intent.identity(), next);
            next = next
                .checked_add(starts)
                .ok_or(ArbitrationError::IntegerOverflow)?;
        }
    }
    Ok((allocated, next))
}

fn aggregate(claims: &[Claim]) -> Result<Vec<Claim>, ArbitrationError> {
    let mut values: BTreeMap<(String, Option<u64>, String), u64> = BTreeMap::new();
    for claim in claims {
        let key = (claim.kind.clone(), claim.owner_id, claim.key.clone());
        let amount = values.get(&key).copied().unwrap_or(0);
        values.insert(
            key,
            amount
                .checked_add(claim.amount)
                .ok_or(ArbitrationError::IntegerOverflow)?,
        );
    }
    Ok(values
        .into_iter()
        .map(|((kind, owner_id, key), amount)| Claim {
            kind,
            key,
            amount,
            owner_id,
        })
        .collect())
}

fn claim_owner(intent: &Intent, claim: &Claim) -> u64 {
    claim.owner_id.unwrap_or_else(|| {
        if claim.kind == "CHILD_SLOT" {
            intent.source_action_instance_id
        } else {
            intent.owner_entity_id
        }
    })
}

fn first_failure(
    intent: &Intent,
    claims: &[Claim],
    releases: &[Claim],
    state: &ArbitrationState,
) -> Result<Option<String>, ArbitrationError> {
    let release_amounts: BTreeMap<CapacityKey, u64> = releases
        .iter()
        .map(|claim| {
            (
                (
                    claim.kind.clone(),
                    claim_owner(intent, claim),
                    claim.key.clone(),
                ),
                claim.amount,
            )
        })
        .collect();
    for claim in claims {
        let owner = claim_owner(intent, claim);
        if claim.kind == "RESOURCE" {
            let available = state
                .resource_banks
                .get(&owner)
                .and_then(|bank| bank.get(&claim.key))
                .copied()
                .unwrap_or(0)
                .checked_add(
                    release_amounts
                        .get(&(claim.kind.clone(), owner, claim.key.clone()))
                        .copied()
                        .unwrap_or(0),
                )
                .ok_or(ArbitrationError::IntegerOverflow)?;
            if claim.amount > available {
                return Ok(Some(format!("RESOURCE_UNAVAILABLE:{owner}:{}", claim.key)));
            }
        } else if claim.kind == "EXCLUSIVE_KEY" {
            if state.exclusive_keys.contains(&claim.key) {
                return Ok(Some(format!("EXCLUSIVE_KEY_UNAVAILABLE:{}", claim.key)));
            }
        } else {
            let key = (claim.kind.clone(), owner, claim.key.clone());
            let capacity = state.capacities.get(&key).copied().unwrap_or(0);
            let usage = state
                .usages
                .get(&key)
                .copied()
                .unwrap_or(0)
                .saturating_sub(release_amounts.get(&key).copied().unwrap_or(0));
            if usage
                .checked_add(claim.amount)
                .ok_or(ArbitrationError::IntegerOverflow)?
                > capacity
            {
                return Ok(Some(format!(
                    "CAPACITY_UNAVAILABLE:{}:{owner}:{}",
                    claim.kind, claim.key
                )));
            }
        }
    }
    Ok(None)
}

fn reserve(
    intent: &Intent,
    claims: &[Claim],
    releases: &[Claim],
    state: &mut ArbitrationState,
) -> Result<(), ArbitrationError> {
    for release in releases {
        let owner = claim_owner(intent, release);
        if release.kind == "RESOURCE" {
            let bank = state.resource_banks.entry(owner).or_default();
            let value = bank.get(&release.key).copied().unwrap_or(0);
            bank.insert(
                release.key.clone(),
                value
                    .checked_add(release.amount)
                    .ok_or(ArbitrationError::IntegerOverflow)?,
            );
        } else if release.kind == "EXCLUSIVE_KEY" {
            state.exclusive_keys.remove(&release.key);
        } else {
            let key = (release.kind.clone(), owner, release.key.clone());
            let value = state.usages.get(&key).copied().unwrap_or(0);
            state
                .usages
                .insert(key, value.saturating_sub(release.amount));
        }
    }
    for claim in claims {
        let owner = claim_owner(intent, claim);
        if claim.kind == "RESOURCE" {
            let bank = state.resource_banks.entry(owner).or_default();
            let value = bank.get(&claim.key).copied().unwrap_or(0);
            bank.insert(
                claim.key.clone(),
                value
                    .checked_sub(claim.amount)
                    .ok_or(ArbitrationError::IntegerOverflow)?,
            );
        } else if claim.kind == "EXCLUSIVE_KEY" {
            state.exclusive_keys.insert(claim.key.clone());
        } else {
            let key = (claim.kind.clone(), owner, claim.key.clone());
            let value = state.usages.get(&key).copied().unwrap_or(0);
            state.usages.insert(
                key,
                value
                    .checked_add(claim.amount)
                    .ok_or(ArbitrationError::IntegerOverflow)?,
            );
        }
    }
    Ok(())
}

fn one() -> u64 {
    1
}

fn default_group() -> String {
    "default".to_owned()
}
