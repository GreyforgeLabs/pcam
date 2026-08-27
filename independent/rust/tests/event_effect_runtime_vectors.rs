use pcam_independent::simulation::{SimulationError, SimulationRuntime, SimulationState};
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/event-effect-runtime.json"))
        .expect("shared event-effect vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_event_effect_queues_delivers_and_restores() {
    let vector = vector();
    let expected = &vector["expected"];
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let mut state = runtime.initial_state(&vector).unwrap();
    let mut digests = Vec::new();
    let mut delivered = Vec::new();
    let mut pending_snapshot = None;
    for (index, tick) in vector["ticks"].as_array().unwrap().iter().enumerate() {
        let trace;
        (state, trace) = runtime.tick(&state, tick).unwrap();
        digests.push(state.digest().unwrap());
        delivered.push(trace.events_delivered);
        if index == 1 {
            pending_snapshot = Some(state.snapshot().unwrap());
            assert_eq!(
                json!(state.pending_events),
                expected["pending_after_emission"]
            );
        }
    }
    let action = &state.action_instances[0];
    let summary = json!({
        "tick": state.tick,
        "node": action.current_node_id,
        "transition_serial": action.transition_serial,
        "pending_events": state.pending_events,
        "event_inbox": action.event_inbox,
        "input_buffer": action.input_buffer,
    });
    assert_eq!(action.definition_hash, expected["definition_hash"]);
    assert_eq!(state.definition_set_hash, expected["definition_set_hash"]);
    assert_eq!(json!(digests), expected["tick_state_digests"]);
    assert_eq!(state.digest().unwrap(), expected["final_state_digest"]);
    assert_eq!(json!(delivered), expected["events_delivered"]);
    assert_eq!(summary, expected["summary"]);

    let restored = SimulationState::restore(&pending_snapshot.unwrap()).unwrap();
    let (continued, trace) = runtime.tick(&restored, &vector["ticks"][2]).unwrap();
    assert_eq!(trace.events_delivered, vec!["1:1:wake"]);
    assert_eq!(continued.digest().unwrap(), expected["final_state_digest"]);
}

#[test]
fn independent_event_effect_rejects_invalid_definitions() {
    let vector = vector();
    for case in vector["definition_fault_cases"].as_array().unwrap() {
        let mut document = vector.clone();
        let effect = document["definitions"][0]["transitions"][1]["effects"][0]
            .as_object_mut()
            .unwrap();
        if let Some(field) = case.get("remove").and_then(Value::as_str) {
            effect.remove(field);
        } else {
            effect.insert(
                case["field"].as_str().unwrap().to_owned(),
                case["value"].clone(),
            );
        }
        let error = SimulationRuntime::from_vector(&document).unwrap_err();
        let SimulationError::Fault(context) = error else {
            panic!("{}: unexpected error", case["id"]);
        };
        assert_eq!(context.code, "DEFINITION_REJECTED", "{}:code", case["id"]);
        assert_eq!(context.fault, case["fault"], "{}:fault", case["id"]);
    }
}

#[test]
fn independent_duplicate_created_event_id_faults_atomically() {
    let vector = vector();
    let mut document = vector.clone();
    document["runtime_profile"]["fault_policy"] = json!("FAULT_ACTION");
    let duplicate = document["definitions"][0]["transitions"][1]["effects"][0].clone();
    document["definitions"][0]["transitions"][1]["effects"]
        .as_array_mut()
        .unwrap()
        .push(duplicate);
    let runtime = SimulationRuntime::from_vector(&document).unwrap();
    let mut state = runtime.initial_state(&document).unwrap();
    let mut digests = Vec::new();
    let mut traces = Vec::new();
    for tick in document["ticks"].as_array().unwrap() {
        let trace;
        (state, trace) = runtime.tick(&state, tick).unwrap();
        digests.push(state.digest().unwrap());
        traces.push(trace);
    }
    let action = &state.action_instances[0];
    let summary = json!({
        "tick": state.tick,
        "node": action.current_node_id,
        "lifecycle": action.lifecycle_state,
        "fault_record": action.fault_record,
        "transition_serial": action.transition_serial,
        "pending_events": state.pending_events,
        "input_buffer": action.input_buffer,
    });
    let case = &vector["runtime_fault_case"];
    assert_eq!(json!(digests), case["tick_state_digests"]);
    assert_eq!(state.digest().unwrap(), case["final_state_digest"]);
    assert_eq!(summary, case["summary"]);
    assert_eq!(traces[1].faults[0]["fault"], case["fault"]);
    assert!(traces[1].effects.is_empty());
}
