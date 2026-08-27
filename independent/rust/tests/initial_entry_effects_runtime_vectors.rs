use pcam_independent::simulation::SimulationRuntime;
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/initial-entry-effects-runtime.json"))
        .expect("shared initial-entry effects vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_initial_entry_effects_match_shared_vector() {
    let vector = vector();
    let expected = &vector["expected"];
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let mut state = runtime.initial_state(&vector).unwrap();
    let mut digests = Vec::new();
    let mut traces = Vec::new();
    for tick in vector["ticks"].as_array().unwrap() {
        let trace;
        (state, trace) = runtime.tick(&state, tick).unwrap();
        digests.push(state.digest().unwrap());
        traces.push(json!({
            "emitted": trace.effects,
            "reduced": trace.reduced,
        }));
    }
    let actions = state
        .action_instances
        .iter()
        .map(|action| {
            (
                action.instance_id.to_string(),
                json!({
                    "definition_hash": action.definition_hash,
                    "lifecycle": action.lifecycle_state,
                    "marker": action.registers["marker"],
                    "emission_serial": action.emission_serial,
                    "transition_serial": action.transition_serial,
                    "parent_instance_id": action.parent_instance_id,
                    "parent_slot_id": action.parent_slot_id,
                    "child_instance_ids": action.child_instance_ids,
                }),
            )
        })
        .collect::<serde_json::Map<_, _>>();
    let summary = json!({
        "tick": state.tick,
        "stamina": state.resource_banks["1"]["STAMINA"],
        "next_action_instance_id": state.next_action_instance_id,
        "actions": actions,
    });
    assert_eq!(state.definition_set_hash, expected["definition_set_hash"]);
    assert_eq!(json!(digests), expected["tick_state_digests"]);
    assert_eq!(state.digest().unwrap(), expected["final_state_digest"]);
    assert_eq!(summary, expected["summary"]);
    assert_eq!(json!(traces), expected["traces"]);
}
