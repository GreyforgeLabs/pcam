use pcam_independent::simulation::SimulationRuntime;
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/redirect-runtime.json"))
        .expect("shared redirect runtime vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_redirect_rebinds_defenses_and_commits_to_final_target() {
    let document = vector();
    let runtime = SimulationRuntime::from_vector(&document).unwrap();
    let initial = runtime.initial_state(&document).unwrap();
    let (state, trace) = runtime.tick(&initial, &document["ticks"][0]).unwrap();
    let summary = json!({
        "resources": state.resource_banks,
        "ledger_count": state.interaction_ledgers.len(),
        "effects": trace.effects.iter().map(|effect| json!([
            effect.effect_class,
            effect.effect_id,
            effect.payload,
            effect.target_entity_id,
        ])).collect::<Vec<_>>(),
        "decision": trace.receipts,
        "reduced": trace.reduced,
    });
    assert_eq!(
        state.definition_set_hash,
        document["definition_set_hash"].as_str().unwrap()
    );
    assert_eq!(
        json!([state.digest().unwrap()]),
        document["tick_state_digests"]
    );
    assert_eq!(
        state.digest().unwrap(),
        document["final_state_digest"].as_str().unwrap()
    );
    assert_eq!(summary, document["expected"]);
}
