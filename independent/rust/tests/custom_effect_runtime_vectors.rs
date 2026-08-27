use pcam_independent::simulation::{
    RetainedRollbackHistory, SimulationError, SimulationRuntime, SimulationState,
};
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/custom-effect-runtime.json"))
        .expect("shared custom effect runtime vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_custom_effect_commits_hashes_and_restores_exactly() {
    let vector = vector();
    let expected = &vector["expected"];
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let mut state = runtime.initial_state(&vector).unwrap();
    let mut digests = Vec::new();
    let mut traces = Vec::new();
    let mut first_snapshot = None;
    for (index, tick) in vector["ticks"].as_array().unwrap().iter().enumerate() {
        let trace;
        (state, trace) = runtime.tick(&state, tick).unwrap();
        digests.push(state.digest().unwrap());
        traces.push(json!({
            "emitted": trace.effects,
            "reduced": trace.reduced,
        }));
        if index == 0 {
            first_snapshot = Some(state.snapshot().unwrap());
        }
    }
    assert_eq!(state.definition_set_hash, expected["definition_set_hash"]);
    assert_eq!(json!(digests), expected["tick_state_digests"]);
    assert_eq!(state.resource_banks["1"]["score"], expected["score"]);
    assert_eq!(state.digest().unwrap(), expected["final_state_digest"]);
    assert_eq!(json!(traces), expected["traces"]);

    let restored = SimulationState::restore(&first_snapshot.unwrap()).unwrap();
    let (continued, trace) = runtime.tick(&restored, &vector["ticks"][1]).unwrap();
    assert_eq!(continued.digest().unwrap(), expected["final_state_digest"]);
    assert_eq!(json!(trace.reduced), expected["traces"][1]["reduced"]);

    let initial = runtime.initial_state(&vector).unwrap();
    let mut history = RetainedRollbackHistory::new(runtime, 4).unwrap();
    let (predicted, _, _) = history.advance(&initial, &vector["ticks"][0]).unwrap();
    let mut predicted_tick = vector["ticks"][1].clone();
    predicted_tick["inputs"] = json!([]);
    let (predicted, _, _) = history.advance(&predicted, &predicted_tick).unwrap();
    assert_eq!(predicted.resource_banks["1"]["score"], 27);
    let correction = history
        .correct_and_resimulate(1, &vector["ticks"][1])
        .unwrap();
    assert_eq!(
        correction.state.digest().unwrap(),
        expected["final_state_digest"]
    );
}

#[test]
fn independent_custom_effect_registry_tampering_and_omission_fail_closed() {
    let vector = vector();
    for (field, value) in [
        ("implementation_hash", json!("0".repeat(64))),
        ("ordering_id", json!("pcam.order.unverified")),
        ("determinism_vectors", json!([])),
        ("payload_schema", json!({"type": "string"})),
    ] {
        let mut document = vector.clone();
        document["custom_effect_registry"][0][field] = value;
        assert!(matches!(
            SimulationRuntime::from_vector(&document),
            Err(SimulationError::InvalidVector)
        ));
    }

    let mut undeclared = vector.clone();
    undeclared["custom_effect_registry"] = json!([]);
    let runtime = SimulationRuntime::from_vector(&undeclared).unwrap();
    let state = runtime.initial_state(&undeclared).unwrap();
    let error = runtime.tick(&state, &undeclared["ticks"][0]).unwrap_err();
    let SimulationError::Fault(context) = error else {
        panic!("expected contextual custom effect fault")
    };
    assert_eq!(context.fault, "UNKNOWN_EFFECT");
}
