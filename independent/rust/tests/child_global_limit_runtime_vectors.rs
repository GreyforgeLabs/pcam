use pcam_independent::simulation::{SimulationError, SimulationRuntime};
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    serde_json::from_slice(
        &fs::read(root.join("tests/vectors/child-global-limit-runtime.json")).unwrap(),
    )
    .unwrap()
}

#[test]
fn independent_child_global_limit_matches_shared_success_and_atomic_fault() {
    let vector = vector();
    for case in vector["cases"].as_array().unwrap() {
        let mut document = vector.clone();
        document["runtime_profile"]["limits"]["max_children_per_action"] =
            case["max_children_per_action"].clone();
        let runtime = SimulationRuntime::from_vector(&document).unwrap();
        let mut state = runtime.initial_state(&document).unwrap();
        let limit = if case.get("fault").is_some() { 2 } else { 3 };
        let mut digests = Vec::new();
        for tick in &document["ticks"].as_array().unwrap()[..limit] {
            (state, _) = runtime.tick(&state, tick).unwrap();
            digests.push(state.digest().unwrap());
        }
        assert_eq!(state.definition_set_hash, case["definition_set_hash"]);
        if case.get("fault").is_some() {
            assert_eq!(state.digest().unwrap(), case["pre_fault_digest"]);
            let error = runtime.tick(&state, &document["ticks"][2]).unwrap_err();
            let SimulationError::Fault(context) = error else {
                panic!("expected child-limit fault")
            };
            assert_eq!(context.fault, case["fault"]);
            assert_eq!(state.digest().unwrap(), case["pre_fault_digest"]);
            continue;
        }
        let summary = json!({
            "next_action_instance_id": state.next_action_instance_id,
            "parents": state.action_instances.iter().map(|a| (a.instance_id.to_string(), json!(a.parent_instance_id))).collect::<serde_json::Map<_, _>>(),
            "parent_slots": state.action_instances.iter().map(|a| (a.instance_id.to_string(), json!(a.parent_slot_id))).collect::<serde_json::Map<_, _>>(),
            "children": state.action_instances.iter().map(|a| (a.instance_id.to_string(), json!(a.child_instance_ids))).collect::<serde_json::Map<_, _>>(),
            "lifecycle": state.action_instances.iter().map(|a| (a.instance_id.to_string(), json!(a.lifecycle_state))).collect::<serde_json::Map<_, _>>(),
        });
        assert_eq!(json!(digests), case["tick_state_digests"]);
        assert_eq!(summary, case["expected"]);
    }
}
