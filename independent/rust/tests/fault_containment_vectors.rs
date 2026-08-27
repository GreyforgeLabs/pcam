use pcam_independent::faults::{FaultContext, contain_fault};
use pcam_independent::simulation::{ActionSnapshot, SimulationState};
use serde::Deserialize;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

#[derive(Deserialize)]
struct VectorFile {
    cases: Vec<Case>,
    abort_cases: Vec<AbortCase>,
}

#[derive(Deserialize)]
struct Case {
    id: String,
    policy: String,
    tick: u64,
    actions: Vec<ActionDocument>,
    fault: FaultContext,
    expected: Value,
}

#[derive(Deserialize)]
struct AbortCase {
    id: String,
    policy: String,
    fault: FaultContext,
}

#[derive(Deserialize)]
struct ActionDocument {
    instance_id: u64,
    owner_entity_id: u64,
    parent_instance_id: Option<u64>,
    parent_slot_id: Option<String>,
    #[serde(default)]
    child_instance_ids: Vec<u64>,
}

fn vectors() -> VectorFile {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/fault-containment.json"))
        .expect("shared fault containment vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

fn base_state(tick: u64, actions: &[ActionDocument]) -> SimulationState {
    SimulationState {
        pcam_version: "3.0".to_owned(),
        action_instances: actions.iter().map(action).collect(),
        action_slots: BTreeMap::new(),
        definition_set_hash: "fault-vector".to_owned(),
        entity_records: BTreeMap::new(),
        extension_state: BTreeMap::new(),
        fault_state: BTreeMap::new(),
        freeze_tokens: Vec::new(),
        host_state: json!({}),
        input_buffers: BTreeMap::new(),
        interaction_ledgers: BTreeMap::new(),
        next_action_instance_id: actions.len() as u64 + 1,
        next_freeze_token_id: 1,
        pending_events: Vec::new(),
        pending_inputs: Vec::new(),
        resource_banks: BTreeMap::new(),
        rng_streams: BTreeMap::new(),
        tick,
    }
}

fn action(value: &ActionDocument) -> ActionSnapshot {
    ActionSnapshot {
        captured_parameters: BTreeMap::new(),
        child_instance_ids: value.child_instance_ids.clone(),
        current_node_id: "RUN".to_owned(),
        current_rate_units: 0,
        cycle: 0,
        deferred_quanta: 0,
        definition_hash: "faultable".to_owned(),
        emission_serial: 0,
        event_inbox: Vec::new(),
        extension_state: BTreeMap::new(),
        fault_record: None,
        freeze_token_references: Vec::new(),
        input_buffer: Vec::new(),
        instance_id: value.instance_id,
        interaction_ledger_partition: "default".to_owned(),
        lifecycle_state: "RUNNING".to_owned(),
        local_step: 0,
        node_step: 0,
        owner_entity_id: value.owner_entity_id,
        parent_instance_id: value.parent_instance_id,
        parent_slot_id: value.parent_slot_id.clone(),
        predicate_entry_serials: BTreeMap::new(),
        predicate_exit_serials: BTreeMap::new(),
        predicate_truth_state: BTreeMap::new(),
        quantum_accumulator: 0,
        registers: BTreeMap::new(),
        rng_stream_ids: Vec::new(),
        slot_claims: Vec::new(),
        transition_serial: 0,
    }
}

fn projection(state: &SimulationState) -> Value {
    json!({
        "tick": state.tick,
        "lifecycle": state.action_instances.iter().map(|action| (action.instance_id.to_string(), json!(action.lifecycle_state))).collect::<serde_json::Map<_, _>>(),
        "fault_records": state.action_instances.iter().map(|action| (action.instance_id.to_string(), json!(action.fault_record))).collect::<serde_json::Map<_, _>>(),
        "parents": state.action_instances.iter().map(|action| (action.instance_id.to_string(), json!(action.parent_instance_id))).collect::<serde_json::Map<_, _>>(),
        "children": state.action_instances.iter().map(|action| (action.instance_id.to_string(), json!(action.child_instance_ids))).collect::<serde_json::Map<_, _>>(),
        "entity_fault_owner": state.entity_records.iter().find(|(_, record)| record.get("fault_record").is_some()).and_then(|(owner, _)| owner.parse::<u64>().ok()),
    })
}

#[test]
fn independent_fault_containment_matches_shared_scope_and_detachment_vectors() {
    for case in vectors().cases {
        let initial = base_state(case.tick, &case.actions);
        let contained = contain_fault(&initial, &case.policy, &case.fault).unwrap();
        assert_eq!(projection(&contained), case.expected, "{}", case.id);
        assert_eq!(
            contained.fault_state["last_fault"]["policy"], case.policy,
            "{}",
            case.id
        );
    }
}

#[test]
fn independent_fault_containment_matches_shared_abort_escalation() {
    let initial = base_state(0, &[]);
    for case in vectors().abort_cases {
        assert!(
            contain_fault(&initial, &case.policy, &case.fault).is_none(),
            "{}",
            case.id
        );
    }
}
