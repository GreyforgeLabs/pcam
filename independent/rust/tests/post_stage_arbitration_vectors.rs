use pcam_independent::simulation::SimulationRuntime;
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/post-stage-arbitration.json"))
        .expect("shared post-stage arbitration vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_post_stage_arbitrates_and_defers_target_progression() {
    let document = vector();
    let runtime = SimulationRuntime::from_vector(&document).unwrap();
    let mut state = runtime.initial_state(&document).unwrap();
    let mut digests = Vec::new();
    let mut target_steps = Vec::new();
    for tick in document["ticks"].as_array().unwrap() {
        (state, _) = runtime.tick(&state, tick).unwrap();
        digests.push(state.digest().unwrap());
        target_steps.push(
            state
                .action_instances
                .iter()
                .find(|action| action.instance_id == 3)
                .map(|action| action.local_step),
        );
    }
    let summary = json!({
        "tick": state.tick,
        "lifecycle": state.action_instances.iter().map(|action| (action.instance_id.to_string(), json!(action.lifecycle_state))).collect::<serde_json::Map<_, _>>(),
        "definitions": state.action_instances.iter().map(|action| (action.instance_id.to_string(), json!(action.definition_hash))).collect::<serde_json::Map<_, _>>(),
        "transition_serials": state.action_instances.iter().map(|action| (action.instance_id.to_string(), json!(action.transition_serial))).collect::<serde_json::Map<_, _>>(),
        "local_steps": state.action_instances.iter().map(|action| (action.instance_id.to_string(), json!(action.local_step))).collect::<serde_json::Map<_, _>>(),
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
        serde_json::to_value(target_steps).unwrap(),
        document["target_steps_after_each_tick"]
    );
    assert_eq!(
        state.digest().unwrap(),
        document["final_state_digest"].as_str().unwrap()
    );
    assert_eq!(summary, document["expected"]);
}
