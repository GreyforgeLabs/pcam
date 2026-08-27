use pcam_independent::simulation::{SimulationError, SimulationRuntime};
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source =
        fs::read(root.join("tests/vectors/nesting-runtime.json")).expect("shared nesting vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_nesting_limit_matches_shared_success_and_atomic_fault() {
    let vector = vector();
    for case in vector["cases"].as_array().unwrap() {
        let mut document = vector.clone();
        document["runtime_profile"]["limits"]["max_action_nesting_depth"] =
            case["max_depth"].clone();
        let runtime = SimulationRuntime::from_vector(&document).unwrap();
        let mut state = runtime.initial_state(&document).unwrap();
        let ticks = document["ticks"].as_array().unwrap();
        let limit = if case["max_depth"] == 2 {
            2
        } else {
            ticks.len()
        };
        let mut digests = Vec::new();
        for tick in &ticks[..limit] {
            (state, _) = runtime.tick(&state, tick).unwrap();
            digests.push(state.digest().unwrap());
        }
        if case["max_depth"] == 2 {
            assert_eq!(state.digest().unwrap(), case["pre_fault_digest"]);
            let error = runtime.tick(&state, &ticks[2]).unwrap_err();
            let SimulationError::Fault(context) = error else {
                panic!("expected contextual nesting fault")
            };
            assert_eq!(context.fault, case["fault"]);
            assert_eq!(state.digest().unwrap(), case["pre_fault_digest"]);
            continue;
        }
        let summary = json!({
            "next_action_instance_id": state.next_action_instance_id,
            "parents": state.action_instances.iter().map(|action| (action.instance_id.to_string(), json!(action.parent_instance_id))).collect::<serde_json::Map<_, _>>(),
            "children": state.action_instances.iter().map(|action| (action.instance_id.to_string(), json!(action.child_instance_ids))).collect::<serde_json::Map<_, _>>(),
            "lifecycle": state.action_instances.iter().map(|action| (action.instance_id.to_string(), json!(action.lifecycle_state))).collect::<serde_json::Map<_, _>>(),
        });
        assert_eq!(
            serde_json::to_value(digests).unwrap(),
            case["tick_state_digests"]
        );
        assert_eq!(summary, case["expected"]);
    }
}
