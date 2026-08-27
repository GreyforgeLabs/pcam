use pcam_independent::action::{
    ActionDefinition, FreezeControls, RuntimeLimits, restore, snapshot, start, tick_with_controls,
};
use pcam_independent::effects::{EffectEnvelope, reduce_effects};
use pcam_independent::interactions::{
    InteractionCandidate, InteractionRule, SemanticFact, canonical_candidates, resolve_candidate,
};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

fn corpus() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/generated/core-properties-v1.json"))
        .expect("shared generated Core corpus");
    serde_json::from_slice(&source).expect("generated corpus JSON")
}

fn rate_definition(case: &Value) -> ActionDefinition {
    serde_json::from_value(json!({
        "id": format!(
            "GENERATED_RATE_{}",
            case["id"].as_str().unwrap().trim_start_matches("rate-")
        ),
        "rate": {
            "scale": case["scale"],
            "units_per_tick": case["units_per_tick"],
        },
        "initial_node": "RUN",
        "nodes": [{"id": "RUN", "mode": "EVENT_DRIVEN"}],
        "transitions": [],
    }))
    .unwrap()
}

fn rate_limits() -> RuntimeLimits {
    RuntimeLimits {
        max_quanta_per_action_per_tick: 128,
        max_internal_transitions_per_tick: 8,
        max_expression_depth: 64,
        max_expression_nodes: 4096,
    }
}

fn advance_rate(
    action: &mut pcam_independent::action::ActionInstance,
    definition: &ActionDefinition,
    start_tick: u64,
    tick_count: u64,
) {
    for tick in start_tick..start_tick + tick_count {
        tick_with_controls(
            action,
            definition,
            rate_limits(),
            tick != 0,
            tick,
            &[],
            &FreezeControls::default(),
        )
        .unwrap();
    }
}

#[test]
fn independent_shared_generated_rates_repeat_and_restore_exactly() {
    let corpus = corpus();
    for case in corpus["rate_restore_cases"].as_array().unwrap() {
        let definition = rate_definition(case);
        let warmup_ticks = case["warmup_ticks"].as_u64().unwrap();
        let continuation_ticks = case["continuation_ticks"].as_u64().unwrap();
        let mut direct = start(&definition).unwrap();
        advance_rate(&mut direct, &definition, 0, warmup_ticks);

        let saved = snapshot(&direct).unwrap();
        let mut restored = restore(&saved, &definition).unwrap();
        advance_rate(&mut direct, &definition, warmup_ticks, continuation_ticks);
        advance_rate(&mut restored, &definition, warmup_ticks, continuation_ticks);
        assert_eq!(restored, direct, "{}:restore", case["id"]);

        let mut repeated = start(&definition).unwrap();
        advance_rate(
            &mut repeated,
            &definition,
            0,
            warmup_ticks + continuation_ticks,
        );
        assert_eq!(repeated, direct, "{}:repeat", case["id"]);
        assert_eq!(
            direct.local_step,
            case["expected_local_step"].as_u64().unwrap(),
            "{}:local-step",
            case["id"]
        );
        assert_eq!(
            direct.quantum_accumulator,
            case["expected_quantum_accumulator"].as_u64().unwrap(),
            "{}:accumulator",
            case["id"]
        );
    }
}

#[test]
fn independent_shared_generated_action_graphs_are_repeatable_and_reach_expected_nodes() {
    let corpus = corpus();
    for case in corpus["action_graph_cases"].as_array().unwrap() {
        let node_count = case["node_count"].as_u64().unwrap();
        let definition: ActionDefinition = serde_json::from_value(json!({
            "id": format!(
                "GENERATED_GRAPH_{}",
                case["id"].as_str().unwrap().trim_start_matches("graph-")
            ),
            "rate": {"scale": 1, "units_per_tick": 1},
            "initial_node": "N0",
            "nodes": (0..node_count)
                .map(|index| json!({"id": format!("N{index}"), "mode": "EVENT_DRIVEN"}))
                .collect::<Vec<_>>(),
            "transitions": (0..node_count - 1)
                .map(|index| json!({
                    "id": format!("T{index}"),
                    "source_node": format!("N{index}"),
                    "evaluation_point": "AFTER_QUANTUM",
                    "priority": 10,
                    "target_kind": "NODE",
                    "target_node": format!("N{}", index + 1),
                }))
                .collect::<Vec<_>>(),
        }))
        .unwrap();
        let ticks = case["ticks"].as_u64().unwrap();
        let mut first = start(&definition).unwrap();
        let mut second = start(&definition).unwrap();
        advance_rate(&mut first, &definition, 0, ticks);
        advance_rate(&mut second, &definition, 0, ticks);
        assert_eq!(first, second, "{}:repeat", case["id"]);
        assert_eq!(
            first.current_node_id, case["expected_node"],
            "{}:node",
            case["id"]
        );
        assert_eq!(
            first.local_step,
            case["expected_local_step"].as_u64().unwrap(),
            "{}:local-step",
            case["id"]
        );
        assert_eq!(
            first.node_step,
            case["expected_node_step"].as_u64().unwrap(),
            "{}:node-step",
            case["id"]
        );
        assert_eq!(
            first.transition_serial,
            case["expected_transition_serial"].as_u64().unwrap(),
            "{}:transition-serial",
            case["id"]
        );
    }
}

#[test]
fn independent_shared_generated_transition_guards_repeat_and_fire() {
    let corpus = corpus();
    for case in corpus["transition_guard_cases"].as_array().unwrap() {
        let definition: ActionDefinition = serde_json::from_value(json!({
            "id": format!(
                "GENERATED_GUARD_{}",
                case["id"].as_str().unwrap().trim_start_matches("guard-")
            ),
            "rate": {"scale": 1, "units_per_tick": 1},
            "initial_node": "RUN",
            "nodes": [
                {"id": "RUN", "mode": "EVENT_DRIVEN"},
                {"id": "DONE", "mode": "EVENT_DRIVEN"},
            ],
            "transitions": [{
                "id": "guarded",
                "source_node": "RUN",
                "evaluation_point": "POST_ADVANCE",
                "priority": 10,
                "target_kind": "NODE",
                "target_node": "DONE",
                "guard_expression": {
                    "op": "gte",
                    "args": [
                        {"ref": "action.node_step"},
                        {"literal": case["threshold"]},
                    ],
                },
            }],
        }))
        .unwrap();
        let ticks = case["ticks"].as_u64().unwrap();
        let mut first = start(&definition).unwrap();
        let mut second = start(&definition).unwrap();
        advance_rate(&mut first, &definition, 0, ticks);
        advance_rate(&mut second, &definition, 0, ticks);
        assert_eq!(first, second, "{}:repeat", case["id"]);
        assert_eq!(
            first.current_node_id, case["expected_node"],
            "{}:node",
            case["id"]
        );
        assert_eq!(
            first.transition_serial,
            case["expected_transition_serial"].as_u64().unwrap(),
            "{}:transition-serial",
            case["id"]
        );
    }
}

#[test]
fn independent_shared_generated_effect_aggregation_is_permutation_invariant() {
    let corpus = corpus();
    for case in corpus["effect_aggregation_cases"].as_array().unwrap() {
        let mut results = Vec::new();
        for field in ["effects", "shuffled_effects"] {
            let effects: Vec<EffectEnvelope> = serde_json::from_value(case[field].clone()).unwrap();
            let (reduced, rejected) = reduce_effects(&effects).unwrap();
            assert!(rejected.is_empty(), "{}:{field}:rejected", case["id"]);
            assert_eq!(reduced.len(), 1, "{}:{field}:count", case["id"]);
            results.push(serde_json::to_value(&reduced[0]).unwrap());
        }
        assert_eq!(results[0], results[1], "{}:permutation", case["id"]);
        assert_eq!(results[0], case["expected"], "{}:expected", case["id"]);
    }
}

#[test]
fn independent_shared_generated_candidate_permutations_have_one_canonical_order() {
    let corpus = corpus();
    for case in corpus["candidate_permutation_cases"].as_array().unwrap() {
        let candidates: Vec<InteractionCandidate> =
            serde_json::from_value(case["candidates"].clone()).unwrap();
        let mut reversed = candidates.clone();
        reversed.reverse();
        for values in [&candidates, &reversed] {
            let ids = canonical_candidates(values)
                .into_iter()
                .map(|candidate| candidate.candidate_id)
                .collect::<Vec<_>>();
            assert_eq!(
                serde_json::to_value(ids).unwrap(),
                case["expected_candidate_ids"],
                "{}",
                case["id"]
            );
        }
    }
}

fn resolve_rule_case(case: &Value, field: &str) -> Value {
    let candidate: InteractionCandidate =
        serde_json::from_value(case["candidate"].clone()).unwrap();
    let offense: SemanticFact = serde_json::from_value(json!({
        "fact_id": "generated-offense",
        "direction": "OFFENSE",
        "channels": [],
        "tags": [],
        "attributes": {},
        "effect_templates": [],
    }))
    .unwrap();
    let rules: Vec<InteractionRule> = serde_json::from_value(case[field].clone()).unwrap();
    let decision = resolve_candidate(
        &candidate,
        &offense,
        &BTreeMap::new(),
        &rules,
        8,
        "FAULT",
        64,
        4096,
    )
    .unwrap();
    json!({
        "status": decision.status,
        "decision_tags": decision.decision_tags,
        "trace_rule_ids": decision
            .trace
            .iter()
            .map(|entry| entry.rule_id.clone())
            .collect::<Vec<_>>(),
    })
}

#[test]
fn independent_shared_generated_rule_sets_ignore_definition_enumeration() {
    let corpus = corpus();
    for case in corpus["interaction_rule_cases"].as_array().unwrap() {
        let expected = json!({
            "status": "ACCEPTED",
            "decision_tags": case["expected_decision_tags"],
            "trace_rule_ids": case["expected_trace_rule_ids"],
        });
        assert_eq!(resolve_rule_case(case, "rules"), expected, "{}", case["id"]);
        assert_eq!(
            resolve_rule_case(case, "shuffled_rules"),
            expected,
            "{}",
            case["id"]
        );
    }
}
