use pcam_independent::simulation::SimulationRuntime;
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/parent-policies.json"))
        .expect("shared parent policy vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_parent_policies_match_shared_domain_specific_outcomes() {
    let vector = vector();
    for case in vector["cases"].as_array().unwrap() {
        let mut document = vector.clone();
        document["definitions"][0]["transitions"][0]["parent_policy"] = case["policy"].clone();
        let runtime = SimulationRuntime::from_vector(&document).unwrap();
        let mut state = runtime.initial_state(&document).unwrap();
        let mut digests = Vec::new();
        for tick in document["ticks"].as_array().unwrap() {
            (state, _) = runtime.tick(&state, tick).unwrap();
            digests.push(state.digest().unwrap());
        }
        let parent = &state.action_instances[0];
        let child = &state.action_instances[1];
        let summary = json!({
            "parent_lifecycle": parent.lifecycle_state,
            "parent_node": parent.current_node_id,
            "parent_local_step": parent.local_step,
            "parent_transition_serial": parent.transition_serial,
            "parent_children": parent.child_instance_ids,
            "child_lifecycle": child.lifecycle_state,
            "child_parent": child.parent_instance_id,
            "freeze_domains": state.freeze_tokens.iter().map(|token| token["domains"].clone()).collect::<Vec<_>>(),
            "freeze_remaining": state.freeze_tokens.iter().map(|token| token["remaining_ticks"].clone()).collect::<Vec<_>>(),
            "next_freeze_token_id": state.next_freeze_token_id,
        });
        assert_eq!(
            serde_json::to_value(digests).unwrap(),
            case["tick_state_digests"],
            "{}:digests",
            case["policy"]
        );
        assert_eq!(summary, case["expected"], "{}:summary", case["policy"]);
    }
}
