use pcam_independent::simulation::{SimulationRuntime, SimulationState};
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/explicit-skip-runtime.json"))
        .expect("shared explicit skip runtime vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_explicit_skip_sets_only_declared_step_and_effect() {
    let vector = vector();
    let expected = &vector["expected"];
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let mut state = runtime.initial_state(&vector).unwrap();
    let mut digests = Vec::new();
    let mut nodes = Vec::new();
    let mut node_steps = Vec::new();
    let mut transition_serials = Vec::new();
    let mut skip_counts = Vec::new();
    for tick in vector["ticks"].as_array().unwrap() {
        let (next, trace) = runtime.tick(&state, tick).unwrap();
        state = next;
        let action = state
            .action_instances
            .iter()
            .find(|action| action.instance_id == 1)
            .unwrap();
        digests.push(Value::String(trace.state_digest));
        nodes.push(Value::String(action.current_node_id.clone()));
        node_steps.push(Value::from(action.node_step));
        transition_serials.push(Value::from(action.transition_serial));
        skip_counts.push(Value::from(state.resource_banks["1"]["skip_count"]));
    }

    assert_eq!(Value::Array(digests), expected["tick_state_digests"]);
    assert_eq!(Value::Array(nodes), expected["node"]);
    assert_eq!(Value::Array(node_steps), expected["node_step"]);
    assert_eq!(
        Value::Array(transition_serials),
        expected["transition_serial"]
    );
    assert_eq!(Value::Array(skip_counts), expected["skip_count"]);
    assert_eq!(
        SimulationState::restore(&state.snapshot().unwrap()).unwrap(),
        state
    );
}
