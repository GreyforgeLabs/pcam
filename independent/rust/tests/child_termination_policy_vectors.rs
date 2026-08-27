use pcam_independent::simulation::{SimulationError, SimulationRuntime};
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/child-termination-policies.json"))
        .expect("shared child termination policy vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_child_termination_policies_match_shared_atomic_outcomes() {
    let vector = vector();
    for case in vector["cases"].as_array().unwrap() {
        let mut document = vector.clone();
        document["definitions"][0]["child_termination_policies"]["SUB"] = case["policy"].clone();
        let runtime = SimulationRuntime::from_vector(&document).unwrap();
        let mut state = runtime.initial_state(&document).unwrap();
        let ticks = document["ticks"].as_array().unwrap();
        let limit = if case["policy"] == "FAULT_IF_OCCUPIED" {
            2
        } else {
            ticks.len()
        };
        let mut digests = Vec::new();
        for tick in &ticks[..limit] {
            (state, _) = runtime.tick(&state, tick).unwrap();
            digests.push(state.digest().unwrap());
        }
        if case["policy"] == "FAULT_IF_OCCUPIED" {
            assert_eq!(state.digest().unwrap(), case["pre_fault_digest"]);
            assert!(matches!(
                runtime.tick(&state, &ticks[2]),
                Err(SimulationError::RuntimeFault)
            ));
            assert_eq!(state.digest().unwrap(), case["pre_fault_digest"]);
            continue;
        }
        let parent = &state.action_instances[0];
        let child = &state.action_instances[1];
        let summary = json!({
            "parent_lifecycle": parent.lifecycle_state,
            "parent_children": parent.child_instance_ids,
            "child_lifecycle": child.lifecycle_state,
            "child_parent": child.parent_instance_id,
            "child_slot": child.parent_slot_id,
            "pending_event_types": state.pending_events.iter().map(|event| event["event_type"].clone()).collect::<Vec<_>>(),
            "child_result_emitted": child.extension_state.get("pcam.child_result_emitted").cloned().unwrap_or_else(|| json!(false)),
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
