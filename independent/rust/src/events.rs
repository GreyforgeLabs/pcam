use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeSet;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EventError {
    StateInvariant,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct EventEnvelope {
    pub event_id: String,
    pub event_type: String,
    pub source_id: u64,
    pub target_id: u64,
    pub origin_tick: u64,
    pub delivery_tick: u64,
    pub payload: Value,
    pub delivery_mode: String,
}

pub fn canonical_events(events: &[EventEnvelope]) -> Result<Vec<EventEnvelope>, EventError> {
    let mut identifiers = BTreeSet::new();
    if events
        .iter()
        .any(|event| !identifiers.insert(event.event_id.as_str()))
    {
        return Err(EventError::StateInvariant);
    }
    let mut ordered = events.to_vec();
    ordered.sort_by(|left, right| {
        left.delivery_tick
            .cmp(&right.delivery_tick)
            .then_with(|| left.target_id.cmp(&right.target_id))
            .then_with(|| {
                left.delivery_mode
                    .as_bytes()
                    .cmp(right.delivery_mode.as_bytes())
            })
            .then_with(|| left.source_id.cmp(&right.source_id))
            .then_with(|| left.event_type.as_bytes().cmp(right.event_type.as_bytes()))
            .then_with(|| left.event_id.as_bytes().cmp(right.event_id.as_bytes()))
    });
    Ok(ordered)
}

pub fn deliver_due(
    events: &[EventEnvelope],
    tick: u64,
    frozen_target_action_ids: &BTreeSet<u64>,
) -> Result<(Vec<EventEnvelope>, Vec<EventEnvelope>), EventError> {
    let mut delivered = Vec::new();
    let mut pending = Vec::new();
    for mut event in canonical_events(events)? {
        if event.delivery_tick < tick {
            return Err(EventError::StateInvariant);
        }
        if event.delivery_tick > tick {
            pending.push(event);
            continue;
        }
        if matches!(
            event.delivery_mode.as_str(),
            "TARGET_ACTION" | "PARENT" | "CHILD"
        ) && frozen_target_action_ids.contains(&event.target_id)
        {
            event.delivery_tick = tick.checked_add(1).ok_or(EventError::StateInvariant)?;
            pending.push(event);
            continue;
        }
        delivered.push(event);
    }
    Ok((canonical_events(&delivered)?, canonical_events(&pending)?))
}
