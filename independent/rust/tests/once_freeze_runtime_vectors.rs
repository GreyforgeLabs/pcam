use pcam_independent::simulation::{SimulationRuntime, SimulationState};
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/once-freeze-runtime.json"))
        .expect("shared once-freeze runtime vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_once_per_action_does_not_rehit_during_or_after_freeze() {
    let vector = vector();
    let expected = &vector["expected"];
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let mut state = runtime.initial_state(&vector).unwrap();
    let mut digests = Vec::new();
    let mut target_hp = Vec::new();
    let mut ledger_count = Vec::new();
    let mut effect_count = Vec::new();
    let mut receipt_count = Vec::new();
    let mut freeze_count = Vec::new();
    for tick in vector["ticks"].as_array().unwrap() {
        let (next, trace) = runtime.tick(&state, tick).unwrap();
        state = next;
        digests.push(Value::String(trace.state_digest));
        target_hp.push(Value::from(state.resource_banks["2"]["hp"]));
        ledger_count.push(Value::from(state.interaction_ledgers.len()));
        effect_count.push(Value::from(trace.effects.len()));
        receipt_count.push(Value::from(trace.receipts.len()));
        freeze_count.push(Value::from(state.freeze_tokens.len()));
    }

    assert_eq!(Value::Array(digests), expected["tick_state_digests"]);
    assert_eq!(Value::Array(target_hp), expected["target_hp"]);
    assert_eq!(Value::Array(ledger_count), expected["ledger_count"]);
    assert_eq!(Value::Array(effect_count), expected["effect_count"]);
    assert_eq!(Value::Array(receipt_count), expected["receipt_count"]);
    assert_eq!(Value::Array(freeze_count), expected["freeze_count"]);
    assert_eq!(
        SimulationState::restore(&state.snapshot().unwrap()).unwrap(),
        state
    );
}
