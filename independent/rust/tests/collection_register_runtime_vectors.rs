use pcam_independent::simulation::SimulationRuntime;
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/collection-register-runtime.json"))
        .expect("shared collection-register vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_collection_register_assignments_match_shared_vector() {
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
        traces.push(trace);
    }
    let action = &state.action_instances[0];
    let summary = json!({
        "tick": state.tick,
        "node": action.current_node_id,
        "registers": action.registers,
        "transition_serial": action.transition_serial,
        "emission_serial": action.emission_serial,
        "input_buffer": action.input_buffer,
    });
    assert_eq!(action.definition_hash, expected["definition_hash"]);
    assert_eq!(state.definition_set_hash, expected["definition_set_hash"]);
    assert_eq!(json!(digests), expected["tick_state_digests"]);
    assert_eq!(state.digest().unwrap(), expected["final_state_digest"]);
    assert_eq!(summary, expected["summary"]);
    assert_eq!(json!(traces.last().unwrap().effects), expected["emitted"]);
}

#[test]
fn independent_collection_assignment_faults_are_tick_atomic() {
    let vector = vector();
    for case in vector["fault_cases"].as_array().unwrap() {
        let mut document = vector.clone();
        document["runtime_profile"]["fault_policy"] = json!("FAULT_ACTION");
        document["definitions"][0]["transitions"][0]["assignments"][3]["target"] =
            case["target"].clone();
        document["definitions"][0]["transitions"][0]["assignments"][3]["value"] =
            case["value"].clone();
        let runtime = SimulationRuntime::from_vector(&document).unwrap();
        let mut state = runtime.initial_state(&document).unwrap();
        let mut digests = Vec::new();
        let mut last_trace = None;
        for tick in document["ticks"].as_array().unwrap() {
            let trace;
            (state, trace) = runtime.tick(&state, tick).unwrap();
            digests.push(state.digest().unwrap());
            last_trace = Some(trace);
        }
        let action = &state.action_instances[0];
        let summary = json!({
            "tick": state.tick,
            "node": action.current_node_id,
            "lifecycle": action.lifecycle_state,
            "fault_record": action.fault_record,
            "registers": action.registers,
            "transition_serial": action.transition_serial,
            "emission_serial": action.emission_serial,
            "input_buffer": action.input_buffer,
        });
        let trace = last_trace.unwrap();
        assert_eq!(
            summary, vector["expected"]["fault_summary"],
            "{}:summary",
            case["id"]
        );
        assert_eq!(
            json!(digests),
            case["tick_state_digests"],
            "{}:ticks:{}",
            case["id"],
            state.snapshot().unwrap()
        );
        assert_eq!(
            state.digest().unwrap(),
            case["final_state_digest"],
            "{}:final",
            case["id"]
        );
        assert_eq!(
            trace.faults[0]["fault"], case["fault"],
            "{}:fault",
            case["id"]
        );
        assert!(trace.effects.is_empty(), "{}:effects", case["id"]);
    }
}
