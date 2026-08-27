use pcam_independent::events::{EventEnvelope, EventError, deliver_due};
use serde::Deserialize;
use std::collections::BTreeSet;
use std::fs;
use std::path::PathBuf;

#[derive(Deserialize)]
struct VectorFile {
    cases: Vec<Case>,
    fault_cases: Vec<FaultCase>,
}

#[derive(Deserialize)]
struct Case {
    id: String,
    tick: u64,
    frozen_target_action_ids: BTreeSet<u64>,
    events: Vec<EventEnvelope>,
    delivered_ids: Vec<String>,
    pending: Vec<EventEnvelope>,
    continuation_tick: Option<u64>,
    continuation_delivered_ids: Option<Vec<String>>,
}

#[derive(Deserialize)]
struct FaultCase {
    id: String,
    tick: u64,
    events: Vec<EventEnvelope>,
    fault: String,
}

fn vectors() -> VectorFile {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/events.json")).expect("shared event vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_event_delivery_matches_shared_order_freeze_and_continuation() {
    for case in vectors().cases {
        let (delivered, pending) =
            deliver_due(&case.events, case.tick, &case.frozen_target_action_ids).unwrap();
        assert_eq!(
            delivered
                .iter()
                .map(|event| event.event_id.clone())
                .collect::<Vec<_>>(),
            case.delivered_ids,
            "{}:delivered",
            case.id
        );
        assert_eq!(pending, case.pending, "{}:pending", case.id);
        if let Some(tick) = case.continuation_tick {
            let (continued, remaining) = deliver_due(&pending, tick, &BTreeSet::new()).unwrap();
            assert_eq!(
                continued
                    .iter()
                    .map(|event| event.event_id.clone())
                    .collect::<Vec<_>>(),
                case.continuation_delivered_ids.unwrap(),
                "{}:continuation",
                case.id
            );
            assert!(remaining.is_empty(), "{}:continuation pending", case.id);
        }
    }
}

#[test]
fn independent_event_delivery_matches_shared_faults() {
    for case in vectors().fault_cases {
        assert_eq!(
            deliver_due(&case.events, case.tick, &BTreeSet::new()).unwrap_err(),
            EventError::StateInvariant,
            "{}:{}",
            case.id,
            case.fault
        );
    }
}
