use pcam_independent::canonicalize;
use pcam_independent::simulation::{SimulationRuntime, SimulationState};
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/state-distinction-runtime.json"))
        .expect("shared state distinction runtime vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

fn branch_snapshot(base: &Value, branch: &Value) -> Value {
    let mut snapshot = base.clone();
    if let Some(remaining_ticks) = branch.get("remaining_ticks") {
        snapshot["freeze_tokens"] = json!([{
            "token_id": 1,
            "source_id": 9,
            "target_id": 1,
            "domains": ["PROGRESSION"],
            "remaining_ticks": remaining_ticks,
            "activation_tick": snapshot["tick"],
            "stack_policy": "INDEPENDENT",
            "stack_group": "state-distinction",
            "accrual_policy": "HOLD",
            "metadata": {"kind": "STALL_COUNTER"},
        }]);
        snapshot["next_freeze_token_id"] = json!(2);
    }
    if let Some(cycle) = branch.get("cycle") {
        snapshot["action_instances"][0]["cycle"] = cycle.clone();
    }
    snapshot
}

#[test]
fn independent_equal_phase_stall_and_cycle_states_serialize_hash_and_continue_distinctly() {
    let vector = vector();
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let initial = runtime.initial_state(&vector).unwrap();
    let (base, _) = runtime.tick(&initial, &vector["ticks"][0]).unwrap();
    let base_snapshot = base.snapshot().unwrap();

    for case in vector["cases"].as_array().unwrap() {
        let mut phases = Vec::new();
        let mut serializations = Vec::new();
        let mut initial_digests = Vec::new();
        let mut summaries = Vec::new();
        for branch in case["branches"].as_array().unwrap() {
            let snapshot = branch_snapshot(&base_snapshot, branch);
            let mut state = SimulationState::restore(&snapshot).unwrap();
            let action = state
                .action_instances
                .iter()
                .find(|action| action.instance_id == 1)
                .unwrap();
            phases.push(json!([
                action.current_node_id,
                action.node_step,
                action.local_step
            ]));
            serializations.push(canonicalize(&state.snapshot().unwrap()).unwrap());
            initial_digests.push(state.digest().unwrap());

            let mut tick_state_digests = Vec::new();
            let mut local_steps = Vec::new();
            let mut cycles = Vec::new();
            let mut remaining_ticks = Vec::new();
            for _ in 0..case["continuation_ticks"].as_u64().unwrap() {
                let trace;
                (state, trace) = runtime.tick(&state, &vector["continuation_tick"]).unwrap();
                let action = state
                    .action_instances
                    .iter()
                    .find(|action| action.instance_id == 1)
                    .unwrap();
                tick_state_digests.push(trace.state_digest);
                local_steps.push(action.local_step);
                cycles.push(action.cycle);
                remaining_ticks.push(
                    state
                        .freeze_tokens
                        .first()
                        .and_then(|token| token["remaining_ticks"].as_u64())
                        .unwrap_or(0),
                );
            }
            let summary = json!({
                "initial_state_digest": initial_digests.last().unwrap(),
                "tick_state_digests": tick_state_digests,
                "local_steps": local_steps,
                "cycles": cycles,
                "remaining_ticks": remaining_ticks,
            });
            assert_eq!(
                summary,
                case["expected"][branch["id"].as_str().unwrap()],
                "{}",
                branch["id"]
            );
            summaries.push(summary);
        }

        assert_eq!(phases[0], phases[1]);
        assert_ne!(serializations[0], serializations[1]);
        assert_ne!(initial_digests[0], initial_digests[1]);
        if case["id"] == "distinct-stall-counters" {
            assert_ne!(
                summaries[0]["local_steps"].as_array().unwrap().last(),
                summaries[1]["local_steps"].as_array().unwrap().last()
            );
        } else {
            assert_ne!(summaries[0]["cycles"], summaries[1]["cycles"]);
        }
    }
}
