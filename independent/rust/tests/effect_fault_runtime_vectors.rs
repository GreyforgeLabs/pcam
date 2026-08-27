use pcam_independent::simulation::{SimulationError, SimulationRuntime};
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/effect-fault-runtime.json"))
        .expect("shared effect fault runtime vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_effect_fault_discards_tick_and_applies_shared_policy() {
    let vector = vector();
    for case in vector["cases"].as_array().unwrap() {
        let mut document = vector.clone();
        document["runtime_profile"]["fault_policy"] = case["policy"].clone();
        let runtime = SimulationRuntime::from_vector(&document).unwrap();
        let mut state = runtime.initial_state(&document).unwrap();
        (state, _) = runtime.tick(&state, &document["ticks"][0]).unwrap();
        assert_eq!(
            state.digest().unwrap(),
            case["pre_fault_digest"].as_str().unwrap(),
            "{}:pre-fault",
            case["policy"]
        );

        if case["policy"] == "ABORT_SIMULATION" {
            let error = runtime.tick(&state, &document["fault_tick"]).unwrap_err();
            let SimulationError::Fault(context) = error else {
                panic!("expected contextual fault")
            };
            assert_eq!(context.fault, case["fault"]);
            assert_eq!(context.message, case["message"]);
            assert_eq!(
                context.action_instance_id,
                case["action_instance_id"].as_u64()
            );
            assert_eq!(context.owner_entity_id, case["owner_entity_id"].as_u64());
            assert_eq!(state.digest().unwrap(), case["pre_fault_digest"]);
            continue;
        }

        let (contained, trace) = runtime.tick(&state, &document["fault_tick"]).unwrap();
        let summary = json!({
            "tick": contained.tick,
            "lifecycle": contained.action_instances.iter().map(|action| (action.instance_id.to_string(), json!(action.lifecycle_state))).collect::<serde_json::Map<_, _>>(),
            "fault_records": contained.action_instances.iter().map(|action| (action.instance_id.to_string(), json!(action.fault_record))).collect::<serde_json::Map<_, _>>(),
            "entity_fault_owners": contained.entity_records.iter().filter(|(_, record)| record.get("fault_record").is_some()).map(|(owner, _)| owner.parse::<u64>().unwrap()).collect::<Vec<_>>(),
            "resources": contained.resource_banks,
            "trace_faults": trace.faults,
            "trace_effects": trace.effects,
            "ledger_count": contained.interaction_ledgers.len(),
        });
        assert_eq!(summary, case["expected"], "{}:summary", case["policy"]);
        assert_eq!(
            contained.digest().unwrap(),
            case["final_state_digest"].as_str().unwrap(),
            "{}:final",
            case["policy"]
        );
    }
}
