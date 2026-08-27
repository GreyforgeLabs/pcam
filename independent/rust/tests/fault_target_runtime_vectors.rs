use pcam_independent::simulation::{SimulationError, SimulationRuntime};
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/fault-target-runtime.json"))
        .expect("shared FAULT target vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_declared_fault_target_matches_shared_vector() {
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
            "faults": trace.faults,
        }));
    }
    let action = &state.action_instances[0];
    let summary = json!({
        "tick": state.tick,
        "lifecycle": action.lifecycle_state,
        "fault_record": action.fault_record,
        "transition_serial": action.transition_serial,
        "emission_serial": action.emission_serial,
        "registers": action.registers,
        "input_buffer": action.input_buffer,
        "stamina": state.resource_banks["1"]["STAMINA"],
    });
    assert_eq!(action.definition_hash, expected["definition_hash"]);
    assert_eq!(state.definition_set_hash, expected["definition_set_hash"]);
    assert_eq!(json!(digests), expected["tick_state_digests"]);
    assert_eq!(state.digest().unwrap(), expected["final_state_digest"]);
    assert_eq!(summary, expected["summary"]);
    let expected_traces = expected["traces"]
        .as_array()
        .unwrap()
        .iter()
        .map(|trace| {
            json!({
                "emitted": trace["emitted"],
                "reduced": trace["reduced"],
                "faults": trace["faults"],
            })
        })
        .collect::<Vec<_>>();
    assert_eq!(traces, expected_traces);
}

#[test]
fn independent_declared_fault_target_rejects_invalid_definitions() {
    let vector = vector();
    for case in vector["definition_fault_cases"].as_array().unwrap() {
        let mut document = vector.clone();
        if let Some(target_kind) = case.get("target_kind") {
            document["definitions"][0]["transitions"][0]["target_kind"] = target_kind.clone();
        }
        if case["fault_code"].is_null() {
            document["definitions"][0]["transitions"][0]
                .as_object_mut()
                .unwrap()
                .remove("fault_code");
        } else {
            document["definitions"][0]["transitions"][0]["fault_code"] = case["fault_code"].clone();
        }
        let error = SimulationRuntime::from_vector(&document).unwrap_err();
        let SimulationError::Fault(context) = error else {
            panic!("{}: unexpected error", case["id"]);
        };
        assert_eq!(context.code, "DEFINITION_REJECTED", "{}:code", case["id"]);
        assert_eq!(context.fault, case["fault"], "{}:fault", case["id"]);
    }
}
