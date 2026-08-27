use pcam_independent::simulation::{SimulationError, SimulationRuntime, SimulationState};
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/rng-call-order-runtime.json"))
        .expect("shared RNG call-order runtime vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

fn execute(document: &Value) -> (SimulationRuntime, SimulationState, Vec<Value>) {
    let runtime = SimulationRuntime::from_vector(document).unwrap();
    let mut state = runtime.initial_state(document).unwrap();
    let mut draws = Vec::new();
    for tick in document["ticks"].as_array().unwrap() {
        let trace;
        (state, trace) = runtime.tick(&state, tick).unwrap();
        draws.push(Value::Array(trace.rng_draws));
    }
    (runtime, state, draws)
}

#[test]
fn independent_shared_rng_call_order_is_permutation_and_restore_invariant() {
    let document = vector();
    let expected = &document["expected"];
    let (runtime, state, draws) = execute(&document);
    assert_eq!(state.definition_set_hash, expected["definition_set_hash"]);
    assert_eq!(json!(draws), expected["rng_draws"]);
    assert_eq!(
        state.rng_streams["shared.simulation"],
        expected["final_stream"]
    );
    assert_eq!(state.digest().unwrap(), expected["final_state_digest"]);

    let mut reversed = document.clone();
    for tick in reversed["ticks"].as_array_mut().unwrap() {
        tick["inputs"].as_array_mut().unwrap().reverse();
    }
    let (_, reversed_state, reversed_draws) = execute(&reversed);
    assert_eq!(reversed_state, state);
    assert_eq!(json!(reversed_draws), expected["rng_draws"]);

    let partial_runtime = SimulationRuntime::from_vector(&document).unwrap();
    let mut partial = partial_runtime.initial_state(&document).unwrap();
    for tick in &document["ticks"].as_array().unwrap()[..2] {
        (partial, _) = partial_runtime.tick(&partial, tick).unwrap();
    }
    let restored = SimulationState::restore(&partial.snapshot().unwrap()).unwrap();
    let (continued, trace) = runtime.tick(&restored, &document["ticks"][2]).unwrap();
    assert_eq!(json!(trace.rng_draws), expected["rng_draws"][2]);
    assert_eq!(continued.digest().unwrap(), expected["final_state_digest"]);
}

#[test]
fn independent_shared_rng_faults_are_tick_atomic() {
    for (mutation, expected_fault) in [
        ("missing-stream", "RNG_PROFILE_MISMATCH"),
        ("draw-count-overflow", "INTEGER_OVERFLOW"),
    ] {
        let mut document = vector();
        if mutation == "missing-stream" {
            document["initial_state"]["rng_streams"] = json!({});
        } else {
            document["initial_state"]["rng_streams"]["shared.simulation"]["draw_count"] =
                json!(u64::MAX);
        }
        let runtime = SimulationRuntime::from_vector(&document).unwrap();
        let initial = runtime.initial_state(&document).unwrap();
        let (state, _) = runtime.tick(&initial, &document["ticks"][0]).unwrap();
        let before = state.clone();
        let error = runtime.tick(&state, &document["ticks"][1]).unwrap_err();
        let SimulationError::Fault(context) = error else {
            panic!("{mutation}: expected contextual RNG fault")
        };
        assert_eq!(context.fault, expected_fault, "{mutation}");
        assert_eq!(state, before, "{mutation}: tick must be atomic");
    }
}

#[test]
fn independent_shared_rng_snapshot_contract_fails_before_execution_and_on_restore() {
    for mutation in [
        "algorithm-mismatch",
        "undeclared-profile",
        "missing-field",
        "wrong-field-type",
        "extra-field",
    ] {
        let mut document = vector();
        if mutation == "algorithm-mismatch" {
            document["initial_state"]["rng_streams"]["shared.simulation"]["algorithm_id"] =
                json!("pcam.unknown.v1");
        } else if mutation == "undeclared-profile" {
            document["runtime_profile"]["rng_profiles"] = json!(["pcam.unknown.v1"]);
        } else if mutation == "missing-field" {
            document["initial_state"]["rng_streams"]["shared.simulation"]
                .as_object_mut()
                .unwrap()
                .remove("stream_selector");
        } else if mutation == "wrong-field-type" {
            document["initial_state"]["rng_streams"]["shared.simulation"]["draw_count"] =
                json!("0");
        } else {
            document["initial_state"]["rng_streams"]["shared.simulation"]["extra"] = json!(0);
        }
        let runtime = SimulationRuntime::from_vector(&document).unwrap();
        assert!(matches!(
            runtime.initial_state(&document),
            Err(SimulationError::InvalidVector)
        ));
    }

    let document = vector();
    let runtime = SimulationRuntime::from_vector(&document).unwrap();
    let state = runtime.initial_state(&document).unwrap();
    let mut snapshot = state.snapshot().unwrap();
    snapshot["rng_streams"]["shared.simulation"]["algorithm_id"] = json!("pcam.unknown.v1");
    assert!(matches!(
        SimulationState::restore(&snapshot),
        Err(SimulationError::RuntimeFault)
    ));
}
