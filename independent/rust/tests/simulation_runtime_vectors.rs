use pcam_independent::simulation::{SimulationRuntime, SimulationState};
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source =
        fs::read(root.join("tests/vectors/typed-strike.json")).expect("shared typed strike vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_simulation_matches_typed_strike_full_state_digests() {
    let vector = vector();
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let initial = runtime.initial_state(&vector).unwrap();
    let restored = SimulationState::restore(&initial.snapshot().unwrap()).unwrap();
    assert_eq!(restored, initial);
    assert_eq!(
        initial.definition_set_hash,
        vector["expected"]["definition_set_hash"].as_str().unwrap()
    );

    let mut state = initial;
    let mut snapshots = Vec::new();
    let mut traces = Vec::new();
    for (index, tick) in vector["ticks"].as_array().unwrap().iter().enumerate() {
        snapshots.push(state.snapshot().unwrap());
        let (next, trace) = runtime.tick(&state, tick).unwrap();
        assert_eq!(
            trace.state_digest,
            vector["expected"]["tick_state_digests"][index]
                .as_str()
                .unwrap(),
            "tick {index}"
        );
        state = next;
        traces.push(trace);
    }
    assert_eq!(
        state.digest().unwrap(),
        vector["expected"]["final_state_digest"].as_str().unwrap()
    );
    assert_eq!(
        state.action_instances[0].definition_hash,
        vector["expected"]["definition_hash"].as_str().unwrap()
    );
    assert_eq!(state.resource_banks["2"]["hp"], 70);
    assert_eq!(state.interaction_ledgers.len(), 1);
    assert_eq!(traces[0].candidate_order, ["c1", "c2"]);
    assert_eq!(traces[0].effects[0].effect_id, "0:1:c1:materialize:0:0");
    assert_eq!(traces[0].receipts[1]["reason"], "ONCE_PER_ACTION_INSTANCE");

    let mut continued = SimulationState::restore(&snapshots[1]).unwrap();
    for tick in &vector["ticks"].as_array().unwrap()[1..] {
        (continued, _) = runtime.tick(&continued, tick).unwrap();
    }
    assert_eq!(continued, state);
}

#[test]
fn independent_simulation_rollback_correction_matches_direct_execution() {
    let vector = vector();
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let initial = runtime.initial_state(&vector).unwrap();
    let initial_snapshot = initial.snapshot().unwrap();
    let mut predicted_tick = vector["ticks"][0].clone();
    predicted_tick["inputs"] = Value::Array(Vec::new());
    let (mut predicted, _) = runtime.tick(&initial, &predicted_tick).unwrap();
    for tick in &vector["ticks"].as_array().unwrap()[1..] {
        (predicted, _) = runtime.tick(&predicted, tick).unwrap();
    }
    assert_eq!(predicted.resource_banks["2"]["hp"], 100);

    let mut corrected = SimulationState::restore(&initial_snapshot).unwrap();
    for tick in vector["ticks"].as_array().unwrap() {
        (corrected, _) = runtime.tick(&corrected, tick).unwrap();
    }
    assert_eq!(
        corrected.digest().unwrap(),
        vector["expected"]["final_state_digest"].as_str().unwrap()
    );
    assert_ne!(corrected, predicted);
}
