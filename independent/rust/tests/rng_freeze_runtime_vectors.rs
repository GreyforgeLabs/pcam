use pcam_independent::simulation::{SimulationRuntime, SimulationState};
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn documents() -> (Value, Value) {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let overlay: Value = serde_json::from_slice(
        &fs::read(root.join("tests/vectors/rng-freeze-runtime.json")).unwrap(),
    )
    .unwrap();
    let mut document: Value = serde_json::from_slice(
        &fs::read(root.join(overlay["base_vector"].as_str().unwrap())).unwrap(),
    )
    .unwrap();
    document["initial_state"]["freeze_tokens"] = json!([overlay["freeze_token"]]);
    document["initial_state"]["next_freeze_token_id"] = json!(2);
    (document, overlay["expected"].clone())
}

#[test]
fn independent_rng_consumption_freeze_is_targeted_expires_and_restores() {
    let (document, expected) = documents();
    let runtime = SimulationRuntime::from_vector(&document).unwrap();
    let mut state = runtime.initial_state(&document).unwrap();
    let mut digests = Vec::new();
    let mut draws = Vec::new();
    let mut saved = None;
    for (index, tick) in document["ticks"].as_array().unwrap().iter().enumerate() {
        let trace;
        (state, trace) = runtime.tick(&state, tick).unwrap();
        digests.push(state.digest().unwrap());
        draws.push(trace.rng_draws);
        if index == 1 {
            saved = Some(state.snapshot().unwrap());
        }
    }
    assert_eq!(state.definition_set_hash, expected["definition_set_hash"]);
    assert_eq!(json!(digests), expected["tick_state_digests"]);
    assert_eq!(json!(draws), expected["rng_draws"]);
    assert_eq!(
        state.rng_streams["shared.simulation"],
        expected["final_stream"]
    );
    assert!(state.freeze_tokens.is_empty());

    let restored = SimulationState::restore(&saved.unwrap()).unwrap();
    let (continued, trace) = runtime.tick(&restored, &document["ticks"][2]).unwrap();
    assert_eq!(json!(trace.rng_draws), expected["rng_draws"][2]);
    assert_eq!(continued.digest().unwrap(), expected["final_state_digest"]);
}
