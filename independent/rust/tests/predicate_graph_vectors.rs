use pcam_independent::action::{
    ActionDefinition, ActionError, FreezeControls, RuntimeLimits, snapshot, start,
    tick_with_controls,
};
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    serde_json::from_slice(&fs::read(root.join("tests/vectors/predicate-graphs.json")).unwrap())
        .unwrap()
}

fn limits(vector: &Value) -> RuntimeLimits {
    RuntimeLimits {
        max_quanta_per_action_per_tick: 8,
        max_internal_transitions_per_tick: 8,
        max_expression_depth: vector["limits"]["max_expression_depth"].as_u64().unwrap() as usize,
        max_expression_nodes: vector["limits"]["max_expression_nodes"].as_u64().unwrap() as usize,
    }
}

fn chain(length: usize) -> Vec<Value> {
    (0..length)
        .map(|index| {
            let expression = if index + 1 == length {
                json!({"literal": true})
            } else {
                json!({"ref": format!("action.predicate.P{:03}", index + 1)})
            };
            json!({"id": format!("P{index:03}"), "expression": expression})
        })
        .collect()
}

fn definition(id: &str, predicates: Vec<Value>, looped: bool) -> ActionDefinition {
    let transition = if looped {
        vec![json!({
            "id": "LOOP",
            "source_node": "A",
            "evaluation_point": "AFTER_QUANTUM",
            "priority": 1,
            "target_kind": "NODE",
            "target_node": "A",
            "target_step": 0,
            "guard_expression": {"op": "gte", "args": [
                {"ref": "action.node_step"}, {"literal": 2}
            ]},
            "consume_policy": "NEVER",
            "cycle_delta": 1
        })]
    } else {
        Vec::new()
    };
    serde_json::from_value(json!({
        "id": id,
        "rate": {"scale": 1, "units_per_tick": if looped { 1 } else { 0 }},
        "initial_node": "A",
        "nodes": [{
            "id": "A",
            "mode": if looped { "TIMED" } else { "EVENT_DRIVEN" },
            "duration_quanta": if looped { Some(2) } else { None },
            "seekable": looped
        }],
        "predicates": predicates,
        "transitions": transition
    }))
    .unwrap()
}

fn fault(error: ActionError) -> &'static str {
    match error {
        ActionError::InvalidDefinition => "DEFINITION_REJECTED",
        ActionError::StateInvariant => "STATE_INVARIANT_FAILURE",
        _ => "OTHER",
    }
}

#[test]
fn independent_predicate_graph_depth_and_node_budgets_are_profile_bound() {
    let vector = vector();
    let limits = limits(&vector);
    for length in vector["accepted_chain_lengths"].as_array().unwrap() {
        let length = length.as_u64().unwrap() as usize;
        let definition = definition(&format!("CHAIN_OK_{length}"), chain(length), false);
        let mut action = start(&definition).unwrap();
        tick_with_controls(
            &mut action,
            &definition,
            limits,
            false,
            0,
            &[],
            &FreezeControls::default(),
        )
        .unwrap();
        assert!(action.predicate_truth_state.values().all(|value| *value));
    }
    for length in vector["rejected_chain_lengths"].as_array().unwrap() {
        let length = length.as_u64().unwrap() as usize;
        let definition = definition(&format!("CHAIN_BAD_{length}"), chain(length), false);
        let mut action = start(&definition).unwrap();
        let before = action.clone();
        let error = tick_with_controls(
            &mut action,
            &definition,
            limits,
            false,
            0,
            &[],
            &FreezeControls::default(),
        )
        .unwrap_err();
        assert_eq!(fault(error), vector["limit_fault"]);
        assert_eq!(action, before);
    }
    for count in vector["rejected_predicate_counts"].as_array().unwrap() {
        let count = count.as_u64().unwrap() as usize;
        let predicates = (0..count)
            .map(|index| json!({"id": format!("P{index:03}"), "expression": {"literal": true}}))
            .collect();
        let definition = definition(&format!("COUNT_BAD_{count}"), predicates, false);
        let mut action = start(&definition).unwrap();
        let error = tick_with_controls(
            &mut action,
            &definition,
            limits,
            false,
            0,
            &[],
            &FreezeControls::default(),
        )
        .unwrap_err();
        assert_eq!(fault(error), vector["limit_fault"]);
    }
}

fn diamond(order: &[Value]) -> Vec<Value> {
    let values = json!({
        "BASE": {"id": "BASE", "expression": {"op": "gte", "args": [
            {"ref": "action.node_step"}, {"literal": 1}
        ]}},
        "LEFT": {"id": "LEFT", "expression": {"ref": "action.predicate.BASE"}},
        "RIGHT": {"id": "RIGHT", "expression": {"ref": "action.predicate.BASE"}},
        "TOP": {"id": "TOP", "expression": {"op": "and", "args": [
            {"ref": "action.predicate.LEFT"}, {"ref": "action.predicate.RIGHT"}
        ]}}
    });
    order
        .iter()
        .map(|identifier| values[identifier.as_str().unwrap()].clone())
        .collect()
}

fn projection(action: &Value) -> Value {
    json!({
        "node_step": action["node_step"],
        "cycle": action["cycle"],
        "truth": action["predicate_truth_state"],
        "entries": action["predicate_entry_serials"],
        "exits": action["predicate_exit_serials"]
    })
}

#[test]
fn independent_diamond_graph_order_edges_and_restore_match_shared_vector() {
    let vector = vector();
    let limits = limits(&vector);
    let mut outcomes = Vec::new();
    for (index, order) in vector["diamond_orders"]
        .as_array()
        .unwrap()
        .iter()
        .enumerate()
    {
        let definition = definition(
            &format!("DIAMOND_{index}"),
            diamond(order.as_array().unwrap()),
            true,
        );
        let mut action = start(&definition).unwrap();
        let mut projections = Vec::new();
        for tick in 0..3 {
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
            let action_snapshot = snapshot(&action).unwrap();
            projections.push(projection(&action_snapshot));
            action = pcam_independent::action::restore(&action_snapshot, &definition).unwrap();
        }
        assert_eq!(&projections, vector["diamond_expected"].as_array().unwrap());
        outcomes.push(projections);
    }
    assert_eq!(outcomes[0], outcomes[1]);
}

#[test]
fn independent_hostile_predicate_cycles_and_missing_dependencies_fail_closed() {
    let vector = vector();
    for case in vector["definition_faults"].as_array().unwrap() {
        let predicates = match case["kind"].as_str().unwrap() {
            "SELF_CYCLE" => vec![json!({"id": "A", "expression": {"ref": "action.predicate.A"}})],
            "THREE_CYCLE" => vec![
                json!({"id": "A", "expression": {"ref": "action.predicate.B"}}),
                json!({"id": "B", "expression": {"ref": "action.predicate.C"}}),
                json!({"id": "C", "expression": {"ref": "action.predicate.A"}}),
            ],
            _ => vec![json!({"id": "A", "expression": {"ref": "action.predicate.MISSING"}})],
        };
        let definition = definition(case["id"].as_str().unwrap(), predicates, false);
        assert_eq!(
            start(&definition).unwrap_err(),
            ActionError::InvalidDefinition
        );
    }
}
