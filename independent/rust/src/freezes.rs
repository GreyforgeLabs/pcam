use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeSet;

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct FreezeToken {
    pub token_id: u64,
    pub source_id: u64,
    pub target_id: u64,
    pub activation_tick: u64,
    pub remaining_ticks: u64,
    pub domains: Vec<String>,
    pub accrual_policy: String,
    pub stack_group: String,
    pub stack_policy: String,
    #[serde(default)]
    pub metadata: Option<Value>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FreezeError {
    InvalidToken,
    DuplicateTokenId,
}

pub fn canonical_tokens(mut tokens: Vec<FreezeToken>) -> Result<Vec<FreezeToken>, FreezeError> {
    let mut identifiers = BTreeSet::new();
    for token in &tokens {
        if token.remaining_ticks == 0
            || token.domains.is_empty()
            || token.domains.iter().collect::<BTreeSet<_>>().len() != token.domains.len()
            || !matches!(token.accrual_policy.as_str(), "HOLD" | "ACCRUE")
            || !matches!(
                token.stack_policy.as_str(),
                "INDEPENDENT" | "MAX_DURATION" | "SUM_DURATION" | "REPLACE" | "REJECT_NEW"
            )
        {
            return Err(FreezeError::InvalidToken);
        }
        if !identifiers.insert(token.token_id) {
            return Err(FreezeError::DuplicateTokenId);
        }
    }
    tokens.sort_by_key(|token| token.token_id);
    Ok(tokens)
}

pub fn add_token(
    tokens: &[FreezeToken],
    mut token: FreezeToken,
) -> Result<Vec<FreezeToken>, FreezeError> {
    let tokens = canonical_tokens(tokens.to_vec())?;
    let group = tokens
        .iter()
        .filter(|existing| {
            existing.target_id == token.target_id && existing.stack_group == token.stack_group
        })
        .collect::<Vec<_>>();
    if token.stack_policy == "REJECT_NEW" && !group.is_empty() {
        return Ok(tokens);
    }
    if token.stack_policy == "REPLACE" {
        let target_id = token.target_id;
        let stack_group = token.stack_group.clone();
        let retained = tokens
            .into_iter()
            .filter(|existing| {
                existing.target_id != target_id || existing.stack_group != stack_group
            })
            .chain(std::iter::once(token))
            .collect();
        return canonical_tokens(retained);
    }
    if matches!(token.stack_policy.as_str(), "MAX_DURATION" | "SUM_DURATION") && !group.is_empty() {
        if group.iter().any(|existing| {
            existing.domains != token.domains
                || existing.accrual_policy != token.accrual_policy
                || existing.stack_policy != token.stack_policy
        }) {
            return Err(FreezeError::InvalidToken);
        }
        if token.stack_policy == "SUM_DURATION" {
            let current_tick = token.activation_tick.saturating_sub(1);
            let latest_expiration = group
                .iter()
                .map(|existing| expiration_exclusive(existing, current_tick))
                .collect::<Result<Vec<_>, _>>()?
                .into_iter()
                .max()
                .ok_or(FreezeError::InvalidToken)?;
            token.activation_tick = token.activation_tick.max(latest_expiration);
        }
    }
    canonical_tokens(tokens.into_iter().chain(std::iter::once(token)).collect())
}

pub fn is_frozen(tokens: &[FreezeToken], tick: u64, target_id: u64, domain: &str) -> bool {
    tokens.iter().any(|token| {
        token.target_id == target_id
            && token.activation_tick <= tick
            && token.remaining_ticks > 0
            && token.domains.iter().any(|value| value == domain)
    })
}

pub fn progression_accrual(
    tokens: &[FreezeToken],
    tick: u64,
    target_id: u64,
) -> Option<&'static str> {
    let mut active = tokens.iter().filter(|token| {
        token.target_id == target_id
            && token.activation_tick <= tick
            && token.remaining_ticks > 0
            && token.domains.iter().any(|value| value == "PROGRESSION")
    });
    let first = active.next()?;
    if first.accrual_policy == "HOLD" || active.any(|token| token.accrual_policy == "HOLD") {
        Some("HOLD")
    } else {
        Some("ACCRUE")
    }
}

pub fn end_tick(tokens: &[FreezeToken], tick: u64) -> Result<Vec<FreezeToken>, FreezeError> {
    let mut updated = Vec::new();
    for token in canonical_tokens(tokens.to_vec())? {
        let mut token = token;
        if token.activation_tick <= tick {
            token.remaining_ticks = token
                .remaining_ticks
                .checked_sub(1)
                .ok_or(FreezeError::InvalidToken)?;
        }
        if token.remaining_ticks > 0 {
            updated.push(token);
        }
    }
    Ok(updated)
}

fn expiration_exclusive(token: &FreezeToken, current_tick: u64) -> Result<u64, FreezeError> {
    let base = if token.activation_tick > current_tick {
        token.activation_tick
    } else {
        current_tick
    };
    base.checked_add(token.remaining_ticks)
        .ok_or(FreezeError::InvalidToken)
}
