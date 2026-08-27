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
            "predicate_truth_state": action.predicate_truth_state,
            "predicate_entry_serials": action.predicate_entry_serials,
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

#[test]
fn independent_ordered_assignment_fault_is_tick_atomic_before_containment() {
    let vector = vector();
    for case in vector["assignment_fault_cases"].as_array().unwrap() {
        let mut document = vector.clone();
        document["runtime_profile"]["fault_policy"] = json!("FAULT_ACTION");
        document["definitions"][0]["register_declarations"]["order"]["maximum"] =
            case["register_maximum"].clone();
        let runtime = SimulationRuntime::from_vector(&document).unwrap();
        let mut state = runtime.initial_state(&document).unwrap();
        let mut digests = Vec::new();
        let mut traces = Vec::new();
        for tick in document["ticks"].as_array().unwrap() {
            let result = runtime.tick(&state, tick).unwrap();
            state = result.0;
            traces.push(result.1);
            digests.push(state.digest().unwrap());
        }
        let action = state
            .action_instances
            .iter()
            .find(|action| action.instance_id == 1)
            .unwrap();
        let summary = json!({
            "tick": state.tick,
            "node": action.current_node_id,
            "lifecycle": action.lifecycle_state,
            "fault_record": action.fault_record,
            "registers": action.registers,
            "input_buffer": action.input_buffer,
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
        assert_eq!(
            traces.last().unwrap().faults[0]["fault"],
            case["fault"],
            "{}:fault",
            case["id"]
        );
        assert_eq!(summary, case["expected"], "{}:summary", case["id"]);
    }
}

#[test]
fn independent_complete_state_rejects_invalid_predicate_graphs() {
    let vector = vector();
    for case in vector["definition_fault_cases"].as_array().unwrap() {
        let mut document = vector.clone();
        document["definitions"][0]["predicates"] = case["predicates"].clone();
        let error = SimulationRuntime::from_vector(&document).unwrap_err();
        let SimulationError::Fault(context) = error else {
            panic!("{}: unexpected error", case["id"]);
        };
        assert_eq!(context.code, "DEFINITION_REJECTED", "{}:code", case["id"]);
        assert_eq!(context.fault, case["fault"], "{}:fault", case["id"]);
    }
}

#[test]
fn independent_complete_state_rejects_invalid_transition_bounds() {
    let vector = vector();
    for case in vector["transition_definition_fault_cases"]
        .as_array()
        .unwrap()
    {
        let mut document = vector.clone();
        for field in ["cycle_delta", "target_step"] {
            if case.get(field).is_some() {
                document["definitions"][0]["transitions"][0][field] = case[field].clone();
            }
        }
        if case.get("target_seekable").is_some() {
            document["definitions"][0]["nodes"][1]["seekable"] = case["target_seekable"].clone();
        }
        if case.get("target_mode").is_some() {
            document["definitions"][0]["nodes"][1]["mode"] = case["target_mode"].clone();
            document["definitions"][0]["nodes"][1]["duration_quanta"] =
                case["target_duration_quanta"].clone();
        }
        let error = SimulationRuntime::from_vector(&document).unwrap_err();
        let SimulationError::Fault(context) = error else {
            panic!("{}: unexpected error", case["id"]);
        };
        assert_eq!(context.code, "DEFINITION_REJECTED", "{}:code", case["id"]);
        assert_eq!(context.fault, case["fault"], "{}:fault", case["id"]);
    }
}

fn structural_fault_document(vector: &Value, case: &Value) -> Value {
    let mut document = vector.clone();
    let transition = document["definitions"][0]["transitions"][0].clone();
    match case["mutation"].as_str().unwrap() {
        "DUPLICATE_PRIORITY" => {
            let mut duplicate = transition;
            duplicate["id"] = json!("duplicate-context-match");
            document["definitions"][0]["transitions"]
                .as_array_mut()
                .unwrap()
                .push(duplicate);
        }
        "MISSING_SOURCE" => {
            document["definitions"][0]["transitions"][0]["source_node"] = json!("MISSING");
        }
        "MISSING_GUARD" => {
            document["definitions"][0]["transitions"][0]["guard_predicate"] = json!("MISSING");
        }
        "AFTER_QUANTUM_CLAIM" => {
            document["definitions"][0]["transitions"][0]["evaluation_point"] =
                json!("AFTER_QUANTUM");
            document["definitions"][0]["transitions"][0]["claims"] =
                json!([{"kind": "RESOURCE", "key": "STAMINA", "amount": 1}]);
        }
        "MISSING_ACTION_TARGET" => {
            let transition = document["definitions"][0]["transitions"][0]
                .as_object_mut()
                .unwrap();
            transition.insert("target_kind".to_owned(), json!("ACTION"));
            transition.insert("target_action".to_owned(), json!("MISSING"));
            transition.remove("target_node");
        }
        mutation => panic!("unexpected mutation: {mutation}"),
    }
    document
}

#[test]
fn independent_complete_state_rejects_invalid_transition_structure() {
    let vector = vector();
    for case in vector["structural_definition_fault_cases"]
        .as_array()
        .unwrap()
    {
        let error =
            SimulationRuntime::from_vector(&structural_fault_document(&vector, case)).unwrap_err();
        let SimulationError::Fault(context) = error else {
            panic!("{}: unexpected error", case["id"]);
        };
        assert_eq!(context.code, "DEFINITION_REJECTED", "{}:code", case["id"]);
        assert_eq!(context.fault, case["fault"], "{}:fault", case["id"]);
    }
}
