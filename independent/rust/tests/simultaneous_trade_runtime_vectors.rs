use pcam_independent::simulation::SimulationRuntime;
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/simultaneous-trade-runtime.json"))
        .expect("shared simultaneous trade runtime vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

fn document(vector: &Value, case: &Value, reverse: bool) -> Value {
    let mut document = vector.clone();
    document["definitions"][0]["semantic_facts"][1]["fact"]["tags"] =
        case["a_defense_tags"].clone();
    if reverse {
        document["ticks"][0]["contacts"]
            .as_array_mut()
            .unwrap()
            .reverse();
    }
    document
}

fn execute(document: &Value) -> (Value, String) {
    let runtime = SimulationRuntime::from_vector(document).unwrap();
    let state = runtime.initial_state(document).unwrap();
    let (state, trace) = runtime.tick(&state, &document["ticks"][0]).unwrap();
    let summary = json!({
        "resources": state.resource_banks,
        "candidate_order": trace.candidate_order,
        "effects": trace.effects.iter().map(|effect| json!([effect.source_entity_id, effect.target_entity_id, effect.payload])).collect::<Vec<_>>(),
    });
    (summary, state.digest().unwrap())
}

#[test]
fn independent_simultaneous_trade_and_armored_outgoing_are_permutation_invariant() {
    let vector = vector();
    for case in vector["cases"].as_array().unwrap() {
        let (forward, forward_digest) = execute(&document(&vector, case, false));
        let (reverse, reverse_digest) = execute(&document(&vector, case, true));

        assert_eq!(forward, case["expected"], "{}:forward", case["id"]);
        assert_eq!(reverse, case["expected"], "{}:reverse", case["id"]);
        assert_eq!(forward_digest, case["final_state_digest"]);
        assert_eq!(reverse_digest, case["final_state_digest"]);
    }
}
