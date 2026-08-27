use pcam_independent::simulation::{SimulationError, SimulationRuntime};
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/transition-context-runtime.json"))
        .expect("shared transition context runtime vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

fn case_document(vector: &Value, case: &Value) -> Value {
    let mut document = vector.clone();
    let declaration = &mut document["definitions"][0]["import_declarations"]["allowed"];
    declaration["failure_policy"] = case["failure_policy"].clone();
    if case.get("default").is_some() {
        declaration["default"] = case["default"].clone();
    } else {
        declaration.as_object_mut().unwrap().remove("default");
    }
    document["ticks"][1]["imports"] = case["imports"].clone();
    document
}

#[test]
fn independent_complete_state_transition_context_matches_shared_vectors() {
    let vector = vector();
    for case in vector["cases"].as_array().unwrap() {
        let document = case_document(&vector, case);
        let runtime = SimulationRuntime::from_vector(&document).unwrap();
        let mut state = runtime.initial_state(&document).unwrap();
        let mut digests = Vec::new();
        for tick in document["ticks"].as_array().unwrap() {
            (state, _) = runtime.tick(&state, tick).unwrap();
            digests.push(state.digest().unwrap());
        }
        let action = state
            .action_instances
            .iter()
            .find(|action| action.instance_id == 1)
            .unwrap();
        let summary = json!({
            "node": action.current_node_id,
            "transition_serial": action.transition_serial,
            "captured_parameters": action.captured_parameters,
            "registers": action.registers,
            "input_buffer": action.input_buffer,
            "host_imports": state.host_state["imports"],
        });
        assert_eq!(
            json!(digests),
            case["tick_state_digests"],
            "{}:ticks",
            case["id"]
        );
        assert_eq!(
            state.digest().unwrap(),
            case["final_state_digest"],
            "{}:final",
            case["id"]
        );
        assert_eq!(summary, case["expected"], "{}:summary", case["id"]);
    }
}

#[test]
fn independent_transition_context_rejects_invalid_host_imports() {
    let vector = vector();
    for case in vector["fault_cases"].as_array().unwrap() {
        let document = case_document(&vector, case);
        let runtime = SimulationRuntime::from_vector(&document).unwrap();
        let mut state = runtime.initial_state(&document).unwrap();
        (state, _) = runtime.tick(&state, &document["ticks"][0]).unwrap();
        let error = runtime.tick(&state, &document["ticks"][1]).unwrap_err();
        let SimulationError::Fault(context) = error else {
            panic!("{}: unexpected error", case["id"]);
        };
        assert_eq!(context.fault, case["fault"], "{}:fault", case["id"]);
    }
}
