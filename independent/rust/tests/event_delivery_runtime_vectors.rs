use pcam_independent::simulation::{SimulationRuntime, SimulationState};
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/event-delivery-runtime.json"))
        .expect("shared event delivery runtime vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

fn event_ids(values: &[Value]) -> Vec<Value> {
    values
        .iter()
        .map(|value| value["event_id"].clone())
        .collect()
}

#[test]
fn independent_complete_tick_routes_and_clears_every_core_event_mode() {
    let vector = vector();
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let initial = runtime.initial_state(&vector).unwrap();
    let (before, first_trace) = runtime.tick(&initial, &vector["ticks"][0]).unwrap();
    let (delivered, delivered_ids) = runtime.deliver_events(&before).unwrap();
    let action = delivered
        .action_instances
        .iter()
        .find(|action| action.instance_id == 1)
        .unwrap();
    let routes = serde_json::json!({
        "action_1": event_ids(&action.event_inbox),
        "entity_1": event_ids(delivered.entity_records["1"]["event_inbox"].as_array().unwrap()),
        "entity_2": event_ids(delivered.entity_records["2"]["event_inbox"].as_array().unwrap()),
    });
    assert_eq!(
        Value::Array(delivered_ids.into_iter().map(Value::String).collect()),
        vector["expected"]["delivered_ids"]
    );
    assert_eq!(routes, vector["expected"]["delivery_routes"]);

    let (final_state, second_trace) = runtime.tick(&before, &vector["ticks"][1]).unwrap();
    let final_action = final_state
        .action_instances
        .iter()
        .find(|action| action.instance_id == 1)
        .unwrap();
    assert_eq!(
        Value::Array(vec![
            Value::String(first_trace.state_digest),
            Value::String(second_trace.state_digest),
        ]),
        vector["expected"]["tick_state_digests"]
    );
    assert_eq!(
        Value::Array(
            second_trace
                .events_delivered
                .into_iter()
                .map(Value::String)
                .collect()
        ),
        vector["expected"]["delivered_ids"]
    );
    assert_eq!(
        final_action.current_node_id,
        vector["expected"]["final_node"]
    );
    assert_eq!(
        final_action.transition_serial,
        vector["expected"]["final_transition_serial"]
            .as_u64()
            .unwrap()
    );
    assert!(final_action.event_inbox.is_empty());
    assert!(
        final_state
            .entity_records
            .values()
            .all(|record| record["event_inbox"].as_array().unwrap().is_empty())
    );
    assert!(final_state.pending_events.is_empty());

    let restored = SimulationState::restore(&final_state.snapshot().unwrap()).unwrap();
    assert_eq!(restored, final_state);
}
