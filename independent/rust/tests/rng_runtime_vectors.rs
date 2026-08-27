use pcam_independent::simulation::{SimulationRuntime, SimulationState};
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source =
        fs::read(root.join("tests/vectors/rng-runtime.json")).expect("shared RNG runtime vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_rng_effect_matches_shared_complete_state_and_restore_continuation() {
    let vector = vector();
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let mut state = runtime.initial_state(&vector).unwrap();
    let mut digests = Vec::new();
    let mut draws = Vec::new();
    for tick in vector["ticks"].as_array().unwrap() {
        let (next, trace) = runtime.tick(&state, tick).unwrap();
        state = next;
        digests.push(Value::String(trace.state_digest));
        draws.push(Value::Array(trace.rng_draws));
    }
    let expected = &vector["expected"];

    assert_eq!(Value::Array(digests), expected["tick_state_digests"]);
    assert_eq!(Value::Array(draws), expected["rng_draws"]);
    assert_eq!(state.rng_streams["main"], expected["final_stream"]);

    let restored = SimulationState::restore(&state.snapshot().unwrap()).unwrap();
    let (continued, trace) = runtime
        .tick(&restored, &vector["continuation_tick"])
        .unwrap();
    assert_eq!(trace.rng_draws, vec![expected["continuation_draw"].clone()]);
    assert_eq!(continued.digest().unwrap(), expected["continuation_digest"]);
}
