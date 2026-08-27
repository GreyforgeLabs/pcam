use pcam_independent::action::{
    ActionDefinition, FreezeControls, RuntimeLimits, snapshot, start, tick_with_controls,
};
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    serde_json::from_slice(&fs::read(root.join("tests/vectors/pcam24-lifecycle.json")).unwrap())
        .unwrap()
}

fn definition(source: &Value, case: &Value) -> ActionDefinition {
    let target = &case["compiled_target"];
    serde_json::from_value(json!({
        "id": source["id"],
        "rate": source["rate"],
        "initial_node": "timeline",
        "nodes": [{
            "id": "timeline",
            "mode": "TIMED",
            "duration_quanta": 24,
            "seekable": true
        }],
        "predicates": [
            {
                "id": "ACTIVE",
                "expression": {"op": "and", "args": [
                    {"op": "gte", "args": [{"ref": "action.node_step"}, {"literal": 10}]},
                    {"op": "lt", "args": [{"ref": "action.node_step"}, {"literal": 14}]}
                ]}
            },
            {
                "id": "RECOVERY",
                "expression": {"op": "and", "args": [
                    {"op": "gte", "args": [{"ref": "action.node_step"}, {"literal": 14}]},
                    {"op": "lt", "args": [{"ref": "action.node_step"}, {"literal": 24}]}
                ]}
            },
            {
                "id": "STARTUP",
                "expression": {"op": "and", "args": [
                    {"op": "gte", "args": [{"ref": "action.node_step"}, {"literal": 0}]},
                    {"op": "lt", "args": [{"ref": "action.node_step"}, {"literal": 10}]}
                ]}
            }
        ],
        "transitions": [{
            "id": format!("timeline_{}", case["lifecycle"].as_str().unwrap().to_lowercase()),
            "source_node": "timeline",
            "evaluation_point": "AFTER_QUANTUM",
            "priority": 100,
            "target_kind": target["kind"],
            "target_node": target.get("node").cloned(),
            "target_step": target.get("target_step").cloned().unwrap_or_else(|| json!(0)),
            "guard_expression": {"op": "gte", "args": [
                {"ref": "action.node_step"}, {"literal": 24}
            ]},
            "consume_policy": "NEVER",
            "assignments": case["compiled_assignments"],
            "cycle_delta": case["compiled_cycle_delta"]
        }]
    }))
    .unwrap()
}

fn projection(snapshot: &Value, expected: &Value) -> Value {
    Value::Object(
        expected
            .as_object()
            .unwrap()
            .keys()
            .map(|key| (key.clone(), snapshot[key].clone()))
            .collect(),
    )
}

#[test]
fn independent_compiled_pcam24_lifecycles_match_shared_projection() {
    let vector = vector();
    let limits = RuntimeLimits {
        max_quanta_per_action_per_tick: vector["limits"]["max_quanta_per_action_per_tick"]
            .as_u64()
            .unwrap(),
        max_internal_transitions_per_tick: vector["limits"]["max_internal_transitions_per_tick"]
            .as_u64()
            .unwrap(),
        max_expression_depth: vector["limits"]["max_expression_depth"].as_u64().unwrap() as usize,
        max_expression_nodes: vector["limits"]["max_expression_nodes"].as_u64().unwrap() as usize,
    };
    for case in vector["cases"].as_array().unwrap() {
        let definition = definition(&vector["source"], case);
        let mut action = start(&definition).unwrap();
        for tick in 0..24 {
            tick_with_controls(
                &mut action,
                &definition,
                limits,
                tick != 0,
                tick,
                &[],
                &FreezeControls::default(),
            )
            .unwrap();
        }
        let action_snapshot = snapshot(&action).unwrap();
        assert_eq!(
            projection(&action_snapshot, &case["expected_projection"]),
            case["expected_projection"],
            "{}",
            case["lifecycle"]
        );
        if case["lifecycle"] == "CLAMP" {
            let before = action.clone();
            tick_with_controls(
                &mut action,
                &definition,
                limits,
                true,
                24,
                &[],
                &FreezeControls::default(),
            )
            .unwrap();
            assert_eq!(action, before);
        }
    }
}
