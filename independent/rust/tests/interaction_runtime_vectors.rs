use pcam_independent::simulation::SimulationRuntime;
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/interaction-runtime.json"))
        .expect("shared interaction runtime vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_interaction_rules_match_shared_complete_tick_outcomes() {
    let vector = vector();
    for case in vector["cases"].as_array().unwrap() {
        let mut document = vector.clone();
        document["definitions"][1]["semantic_facts"][0]["fact"]["tags"] =
            case["defense_tags"].clone();
        let runtime = SimulationRuntime::from_vector(&document).unwrap();
        let initial = runtime.initial_state(&document).unwrap();
        let (state, trace) = runtime.tick(&initial, &document["ticks"][0]).unwrap();
        let summary = json!({
            "resources": state.resource_banks["2"],
            "ledger_count": state.interaction_ledgers.len(),
            "effects": trace.effects.iter().map(|effect| json!([effect.effect_class, effect.effect_id, effect.payload])).collect::<Vec<_>>(),
            "decision": trace.receipts,
            "reduced": trace.reduced,
        });
        assert_eq!(
            json!([state.digest().unwrap()]),
            case["tick_state_digests"],
            "{}:digest",
            case["id"]
        );
        assert_eq!(summary, case["expected"], "{}:summary", case["id"]);
    }
}
