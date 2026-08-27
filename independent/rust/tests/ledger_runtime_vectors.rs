use pcam_independent::simulation::SimulationRuntime;
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/ledger-runtime.json"))
        .expect("shared ledger runtime vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_complete_runtime_matches_shared_ledger_policy_outcomes() {
    let vector = vector();
    for case in vector["cases"].as_array().unwrap() {
        let mut document = vector.clone();
        document["definitions"][0]["semantic_facts"][0]["hit_policy"] = case["policy"].clone();
        document["ticks"] = case["ticks"].clone();
        let runtime = SimulationRuntime::from_vector(&document).unwrap();
        let mut state = runtime.initial_state(&document).unwrap();
        let mut digests = Vec::new();
        let mut effects_by_tick = Vec::new();
        let mut accepted_by_tick = Vec::new();
        let mut receipt_written_by_tick = Vec::new();
        let mut reasons_by_tick = Vec::new();
        for tick in document["ticks"].as_array().unwrap() {
            let trace;
            (state, trace) = runtime.tick(&state, tick).unwrap();
            digests.push(state.digest().unwrap());
            effects_by_tick.push(
                trace
                    .effects
                    .iter()
                    .map(|effect| effect.effect_id.clone())
                    .collect::<Vec<_>>(),
            );
            accepted_by_tick.push(
                trace
                    .receipts
                    .iter()
                    .map(|receipt| receipt["accepted"].clone())
                    .collect::<Vec<_>>(),
            );
            receipt_written_by_tick.push(
                trace
                    .receipts
                    .iter()
                    .map(|receipt| {
                        receipt
                            .get("receipt_written")
                            .cloned()
                            .unwrap_or(Value::Null)
                    })
                    .collect::<Vec<_>>(),
            );
            reasons_by_tick.push(
                trace
                    .receipts
                    .iter()
                    .map(|receipt| receipt.get("reason").cloned().unwrap_or(Value::Null))
                    .collect::<Vec<_>>(),
            );
        }
        let action = state
            .action_instances
            .iter()
            .find(|action| action.instance_id == 1)
            .unwrap();
        let mut ledger_origin_ticks = state
            .interaction_ledgers
            .values()
            .map(|receipt| receipt["origin_tick"].as_u64().unwrap())
            .collect::<Vec<_>>();
        ledger_origin_ticks.sort_unstable();
        let summary = json!({
            "hp": state.resource_banks["2"]["hp"],
            "ledger_count": state.interaction_ledgers.len(),
            "ledger_origin_ticks": ledger_origin_ticks,
            "effects_by_tick": effects_by_tick,
            "accepted_by_tick": accepted_by_tick,
            "receipt_written_by_tick": receipt_written_by_tick,
            "reasons_by_tick": reasons_by_tick,
            "predicate_entry_serials": action.predicate_entry_serials,
            "predicate_exit_serials": action.predicate_exit_serials,
        });
        assert_eq!(
            action.definition_hash,
            case["definition_hash"].as_str().unwrap(),
            "{}:definition",
            case["id"]
        );
        assert_eq!(
            state.definition_set_hash,
            case["definition_set_hash"].as_str().unwrap(),
            "{}:definition-set",
            case["id"]
        );
        assert_eq!(
            serde_json::to_value(digests).unwrap(),
            case["tick_state_digests"],
            "{}:ticks",
            case["id"]
        );
        assert_eq!(
            state.digest().unwrap(),
            case["final_state_digest"].as_str().unwrap(),
            "{}:final",
            case["id"]
        );
        assert_eq!(summary, case["expected"], "{}:summary", case["id"]);
    }
}
