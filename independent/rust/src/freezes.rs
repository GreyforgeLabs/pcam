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
