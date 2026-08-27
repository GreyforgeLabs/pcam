use pcam_independent::simulation::SimulationRuntime;
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/transition-context-runtime.json"))
        .expect("shared transition context runtime vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_complete_state_transition_context_matches_shared_vectors() {
    let vector = vector();
    for case in vector["cases"].as_array().unwrap() {
        let mut document = vector.clone();
        document["ticks"][1]["imports"]["allowed"] = case["allowed"].clone();
        let runtime = SimulationRuntime::from_vector(&document).unwrap();
        let mut state = runtime.initial_state(&document).unwrap();
        let mut digests = Vec::new();
        for tick in document["ticks"].as_array().unwrap() {
            (state, _) = runtime.tick(&state, tick).unwrap();
            digests.push(state.digest().unwrap());
        }
        let action = state
            .action_instances
            .iter()
            .find(|action| action.instance_id == 1)
            .unwrap();
        let summary = json!({
            "node": action.current_node_id,
            "transition_serial": action.transition_serial,
            "input_buffer": action.input_buffer,
            "host_imports": state.host_state["imports"],
        });
        assert_eq!(
            json!(digests),
            case["tick_state_digests"],
            "{}:ticks",
            case["id"]
        );
        assert_eq!(
            state.digest().unwrap(),
            case["final_state_digest"],
            "{}:final",
            case["id"]
        );
        assert_eq!(summary, case["expected"], "{}:summary", case["id"]);
    }
}
