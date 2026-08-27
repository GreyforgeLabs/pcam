use crate::simulation::SimulationState;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::BTreeSet;

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct FaultContext {
    pub code: String,
    pub fault: String,
    pub message: String,
    pub action_instance_id: Option<u64>,
    pub owner_entity_id: Option<u64>,
}

pub fn contain_fault(
    state: &SimulationState,
    policy: &str,
    context: &FaultContext,
) -> Option<SimulationState> {
    if policy == "ABORT_SIMULATION" {
        return None;
    }
    let action = context.action_instance_id.and_then(|identifier| {
        state
            .action_instances
            .iter()
            .find(|action| action.instance_id == identifier)
    });
    let owner_entity_id = context
        .owner_entity_id
        .or_else(|| action.map(|action| action.owner_entity_id));
    if policy == "FAULT_ACTION" && action.is_none() {
        return None;
    }
    if policy == "FAULT_ENTITY" && owner_entity_id.is_none() {
        return None;
    }
    let mut work = state.clone();
    let record = json!({
        "action_instance_id": action.map(|action| action.instance_id),
        "code": context.code,
        "contained": true,
        "fault": context.fault,
        "message": context.message,
        "owner_entity_id": owner_entity_id,
        "policy": policy,
        "tick": state.tick,
    });
    if policy == "FAULT_ACTION" {
        let identifier = action?.instance_id;
        let target = work
            .action_instances
            .iter_mut()
            .find(|action| action.instance_id == identifier)?;
        target.lifecycle_state = "FAULTED".to_owned();
        target.fault_record = Some(context.fault.clone());
    } else if policy == "FAULT_ENTITY" {
        let owner = owner_entity_id?;
        let faulted_ids = work
            .action_instances
            .iter()
            .filter(|action| {
                action.owner_entity_id == owner
                    && !matches!(action.lifecycle_state.as_str(), "TERMINATED" | "FAULTED")
            })
            .map(|action| action.instance_id)
            .collect::<BTreeSet<_>>();
        for action in &mut work.action_instances {
            if faulted_ids.contains(&action.instance_id) {
                action.lifecycle_state = "FAULTED".to_owned();
                action.fault_record = Some(context.fault.clone());
                action
                    .child_instance_ids
                    .retain(|child| faulted_ids.contains(child));
                if action
                    .parent_instance_id
                    .is_some_and(|parent| !faulted_ids.contains(&parent))
                {
                    action.parent_instance_id = None;
                    action.parent_slot_id = None;
                }
            } else {
                if action
                    .parent_instance_id
                    .is_some_and(|parent| faulted_ids.contains(&parent))
                {
                    action.parent_instance_id = None;
                    action.parent_slot_id = None;
                }
                action
                    .child_instance_ids
                    .retain(|child| !faulted_ids.contains(child));
            }
        }
        work.entity_records
            .entry(owner.to_string())
            .or_insert_with(|| json!({}))["fault_record"] = record.clone();
        work.freeze_tokens.retain(|token| {
            token
                .get("target_id")
                .and_then(Value::as_u64)
                .is_none_or(|target| !faulted_ids.contains(&target))
        });
    } else {
        return None;
    }
    work.fault_state.insert("last_fault".to_owned(), record);
    work.tick = state.tick.checked_add(1)?;
    Some(work)
}
