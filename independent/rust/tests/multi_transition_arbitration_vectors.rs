use pcam_independent::simulation::SimulationRuntime;
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/multi-transition-arbitration.json"))
        .expect("shared multi-transition arbitration vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_pre_stage_arbitrates_simultaneous_transitions_together() {
    let document = vector();
    let runtime = SimulationRuntime::from_vector(&document).unwrap();
    let mut state = runtime.initial_state(&document).unwrap();
    let mut digests = Vec::new();
    for tick in document["ticks"].as_array().unwrap() {
        (state, _) = runtime.tick(&state, tick).unwrap();
        digests.push(state.digest().unwrap());
    }
    let summary = json!({
        "tick": state.tick,
        "lifecycle": state.action_instances.iter().map(|action| (action.instance_id.to_string(), json!(action.lifecycle_state))).collect::<serde_json::Map<_, _>>(),
        "definitions": state.action_instances.iter().map(|action| (action.instance_id.to_string(), json!(action.definition_hash))).collect::<serde_json::Map<_, _>>(),
        "transition_serials": state.action_instances.iter().map(|action| (action.instance_id.to_string(), json!(action.transition_serial))).collect::<serde_json::Map<_, _>>(),
        "stamina": state.resource_banks["1"]["STAMINA"],
        "slot": state.action_slots["1"]["FULL_BODY"],
        "next_action_instance_id": state.next_action_instance_id,
    });
    assert_eq!(
        state.definition_set_hash,
        document["definition_set_hash"].as_str().unwrap()
    );
    assert_eq!(
        serde_json::to_value(digests).unwrap(),
        document["tick_state_digests"]
    );
    assert_eq!(
        state.digest().unwrap(),
        document["final_state_digest"].as_str().unwrap()
    );
    assert_eq!(summary, document["expected"]);
}
