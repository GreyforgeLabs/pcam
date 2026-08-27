use pcam_independent::action::{
    ActionDefinition, FreezeControls, RuntimeLimits, TickInput, restore, snapshot, start,
    tick_with_controls,
};
use pcam_independent::canonical_hash;
use pcam_independent::effects::{EffectEnvelope, reduce_effects};
use pcam_independent::freezes::{
    FreezeToken, canonical_tokens, end_tick, is_frozen, progression_accrual,
};
use pcam_independent::interactions::{
    InteractionCandidate, InteractionRule, SemanticFact, canonical_candidates, resolve_candidate,
};
use pcam_independent::simulation::{RetainedRollbackHistory, SimulationRuntime, SimulationState};
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
            canonical_hash(&serde_json::to_value(&first).unwrap()).unwrap(),
            canonical_hash(&serde_json::to_value(&second).unwrap()).unwrap(),
            "{}:digest",
            case["id"]
        );
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
fn independent_shared_generated_input_orders_produce_one_buffer_snapshot() {
    let corpus = corpus();
    for case in corpus["input_order_cases"].as_array().unwrap() {
        let definition: ActionDefinition = serde_json::from_value(json!({
            "id": format!(
                "GENERATED_INPUT_{}",
                case["id"]
                    .as_str()
                    .unwrap()
                    .trim_start_matches("input-order-")
            ),
            "rate": {"scale": 1, "units_per_tick": 0},
            "initial_node": "RUN",
            "nodes": [{"id": "RUN", "mode": "EVENT_DRIVEN"}],
            "transitions": [],
            "buffer_capacity": 8,
            "default_buffer_lifetime": 3,
        }))
        .unwrap();
        let original: Vec<TickInput> = serde_json::from_value(case["inputs"].clone()).unwrap();
        let shuffled: Vec<TickInput> =
            serde_json::from_value(case["shuffled_inputs"].clone()).unwrap();
        let mut reversed = original.clone();
        reversed.reverse();
        let mut states = Vec::new();
        for inputs in [&original, &shuffled, &reversed] {
            let mut action = start(&definition).unwrap();
            tick_with_controls(
                &mut action,
                &definition,
                rate_limits(),
                false,
                0,
                &[],
                &FreezeControls::default(),
            )
            .unwrap();
            tick_with_controls(
                &mut action,
                &definition,
                rate_limits(),
                true,
                1,
                inputs,
                &FreezeControls::default(),
            )
            .unwrap();
            states.push(action);
        }
        assert_eq!(states[0], states[1], "{}:shuffled", case["id"]);
        assert_eq!(states[0], states[2], "{}:reversed", case["id"]);
        let input_ids = states[0]
            .input_buffer
            .iter()
            .map(|entry| entry.input_id.clone())
            .collect::<Vec<_>>();
        assert_eq!(
            serde_json::to_value(input_ids).unwrap(),
            case["expected_input_ids"],
            "{}:order",
            case["id"]
        );
        assert!(
            states[0]
                .input_buffer
                .iter()
                .all(|entry| entry.remaining_eligibility_ticks == 2),
            "{}:ttl",
            case["id"]
        );
    }
}

#[test]
fn independent_shared_generated_freeze_token_combinations_match_timing_and_domains() {
    let corpus = corpus();
    let domains = ["BUFFER_EXPIRY", "INPUT_CAPTURE", "PROGRESSION"];
    for case in corpus["freeze_token_cases"].as_array().unwrap() {
        let mut runs = Vec::new();
        for field in ["tokens", "shuffled_tokens"] {
            let parsed: Vec<FreezeToken> = serde_json::from_value(case[field].clone()).unwrap();
            let mut tokens = canonical_tokens(parsed).unwrap();
            let mut observations = Vec::new();
            for expected in case["expected_ticks"].as_array().unwrap() {
                let tick = expected["tick"].as_u64().unwrap();
                let mut targets = serde_json::Map::new();
                for target_id in [1_u64, 2] {
                    let domain_state = domains
                        .iter()
                        .map(|domain| {
                            (
                                (*domain).to_owned(),
                                Value::Bool(is_frozen(&tokens, tick, target_id, domain)),
                            )
                        })
                        .collect();
                    targets.insert(
                        target_id.to_string(),
                        json!({
                            "domains": Value::Object(domain_state),
                            "progression_accrual": progression_accrual(
                                &tokens, tick, target_id
                            ),
                        }),
                    );
                }
                tokens = end_tick(&tokens, tick).unwrap();
                observations.push(json!({
                    "tick": tick,
                    "targets": targets,
                    "remaining_after_tick": tokens
                        .iter()
                        .map(|token| json!({
                            "token_id": token.token_id,
                            "remaining_ticks": token.remaining_ticks,
                        }))
                        .collect::<Vec<_>>(),
                }));
            }
            runs.push(Value::Array(observations));
        }
        assert_eq!(runs[0], runs[1], "{}:permutation", case["id"]);
        assert_eq!(runs[0], case["expected_ticks"], "{}:expected", case["id"]);
    }
}

fn rollback_vector(case: &Value) -> Value {
    json!({
        "runtime_profile": {
            "pcam_version": "3.0",
            "kind": "runtime_profile",
            "id": format!("pcam.generated.{}.v1", case["id"].as_str().unwrap()),
            "revision": 1,
            "fault_policy": "ABORT_SIMULATION",
            "limits": {
                "max_actions_per_entity": 8,
                "max_action_nesting_depth": 4,
                "max_children_per_action": 4,
                "max_quanta_per_action_per_tick": 16,
                "max_internal_transitions_per_action_per_tick": 8,
                "max_buffer_entries_per_action": 8,
                "max_pending_events_per_entity": 8,
                "max_candidates_per_tick": 32,
                "max_effects_per_tick": 32,
                "max_redirects_per_candidate": 4,
                "max_definition_size_bytes": 65536,
                "max_snapshot_size_bytes": 262144,
                "max_extension_state_bytes": 4096,
                "max_expression_depth": 64,
                "max_expression_nodes": 4096,
            },
            "rng_profiles": ["pcam.pcg32.v1"],
            "network_profiles": [{
                "id": "pcam.local.v1",
                "topology": "LOCAL_DETERMINISTIC",
            }],
            "extensions": {},
        },
        "definitions": [{
            "id": format!(
                "GENERATED_ROLLBACK_{}",
                case["id"]
                    .as_str()
                    .unwrap()
                    .trim_start_matches("rollback-correction-")
            ),
            "rate_scale": case["scale"],
            "units_per_tick": case["units_per_tick"],
            "initial_node_id": "RUN",
            "nodes": [{"id": "RUN", "mode": "EVENT_DRIVEN"}],
        }],
        "interaction_rules": [],
        "effect_registry": {},
        "initial_state": {},
    })
}

fn rollback_tick(case: &Value, tick: u64, has_start: bool) -> Value {
    let inputs = if tick == case["corrected_tick"].as_u64().unwrap() && has_start {
        vec![json!({
            "input_id": format!("start-{}", case["id"].as_str().unwrap()),
            "source_entity_id": 1,
            "sequence": 0,
            "command_id": "START",
            "assigned_tick": tick,
            "action_definition_id": format!(
                "GENERATED_ROLLBACK_{}",
                case["id"]
                    .as_str()
                    .unwrap()
                    .trim_start_matches("rollback-correction-")
            ),
        })]
    } else {
        Vec::new()
    };
    json!({"inputs": inputs, "contacts": []})
}

#[test]
fn independent_shared_generated_rollback_corrections_match_direct_execution() {
    let corpus = corpus();
    for case in corpus["rollback_correction_cases"].as_array().unwrap() {
        let vector = rollback_vector(case);
        let runtime = SimulationRuntime::from_vector(&vector).unwrap();
        let initial = runtime.initial_state(&vector).unwrap();
        let mut manager = RetainedRollbackHistory::new(
            runtime.clone(),
            case["total_ticks"].as_u64().unwrap() + 1,
        )
        .unwrap();
        let mut predicted = initial.clone();
        let mut direct = initial;
        for tick in 0..case["total_ticks"].as_u64().unwrap() {
            let predicted_document =
                rollback_tick(case, tick, case["predicted_has_start"].as_bool().unwrap());
            let corrected_document =
                rollback_tick(case, tick, case["corrected_has_start"].as_bool().unwrap());
            (predicted, _, _) = manager.advance(&predicted, &predicted_document).unwrap();
            (direct, _) = runtime.tick(&direct, &corrected_document).unwrap();
        }
        let corrected_document = rollback_tick(
            case,
            case["corrected_tick"].as_u64().unwrap(),
            case["corrected_has_start"].as_bool().unwrap(),
        );
        let correction = manager
            .correct_and_resimulate(
                case["corrected_tick"].as_u64().unwrap(),
                &corrected_document,
            )
            .unwrap();
        assert_eq!(correction.state, direct, "{}:state", case["id"]);
        assert_eq!(
            correction.rewind_ticks,
            case["expected_rewind_ticks"].as_u64().unwrap(),
            "{}:rewind",
            case["id"]
        );
        assert_eq!(
            correction.state.action_instances.len() as u64,
            case["expected_action_count"].as_u64().unwrap(),
            "{}:action-count",
            case["id"]
        );
        if let Some(action) = correction.state.action_instances.first() {
            assert_eq!(
                action.local_step,
                case["expected_local_step"].as_u64().unwrap(),
                "{}:local-step",
                case["id"]
            );
            assert_eq!(
                action.quantum_accumulator,
                case["expected_quantum_accumulator"].as_u64().unwrap(),
                "{}:accumulator",
                case["id"]
            );
        }
    }
}

fn parent_child_vector(case: &Value) -> Value {
    let suffix = case["id"]
        .as_str()
        .unwrap()
        .trim_start_matches("parent-child-");
    let slot = case["child_slot_id"].as_str().unwrap();
    let child_slot_capacities = BTreeMap::from([(slot.to_owned(), case["capacity"].clone())]);
    let child_termination_policies =
        BTreeMap::from([(slot.to_owned(), Value::String("TERMINATE_CHILD".to_owned()))]);
    json!({
        "runtime_profile": {
            "pcam_version": "3.0",
            "kind": "runtime_profile",
            "id": format!("pcam.generated.{}.v1", case["id"].as_str().unwrap()),
            "revision": 1,
            "fault_policy": "ABORT_SIMULATION",
            "limits": {
                "max_actions_per_entity": 8,
                "max_action_nesting_depth": 4,
                "max_children_per_action": case["capacity"],
                "max_quanta_per_action_per_tick": 8,
                "max_internal_transitions_per_action_per_tick": 8,
                "max_buffer_entries_per_action": 8,
                "max_pending_events_per_entity": 8,
                "max_candidates_per_tick": 32,
                "max_effects_per_tick": 32,
                "max_redirects_per_candidate": 4,
                "max_definition_size_bytes": 65536,
                "max_snapshot_size_bytes": 262144,
                "max_extension_state_bytes": 4096,
                "max_expression_depth": 64,
                "max_expression_nodes": 4096,
            },
            "rng_profiles": ["pcam.pcg32.v1"],
            "network_profiles": [{
                "id": "pcam.local.v1",
                "topology": "LOCAL_DETERMINISTIC",
            }],
            "extensions": {},
        },
        "definitions": [
            {
                "id": format!("GENERATED_PARENT_{suffix}"),
                "rate_scale": 1,
                "units_per_tick": 0,
                "initial_node_id": "RUN",
                "nodes": [{"id": "RUN", "mode": "EVENT_DRIVEN"}],
                "child_slot_capacities": child_slot_capacities,
                "child_termination_policies": child_termination_policies,
                "transitions": [{
                    "id": "launch",
                    "source_node": "RUN",
                    "evaluation_point": "PRE_ADVANCE",
                    "priority": 10,
                    "target_kind": "CHILD_ACTION",
                    "target_action": format!("GENERATED_CHILD_{suffix}"),
                    "child_slot_id": slot,
                    "parent_policy": "CONTINUE",
                    "input_command": "LAUNCH",
                }],
            },
            {
                "id": format!("GENERATED_CHILD_{suffix}"),
                "rate_scale": 1,
                "units_per_tick": 0,
                "initial_node_id": "RUN",
                "nodes": [{"id": "RUN", "mode": "EVENT_DRIVEN"}],
            },
        ],
        "interaction_rules": [],
        "effect_registry": {},
        "initial_state": {},
    })
}

fn run_parent_child_case(case: &Value) -> (SimulationRuntime, SimulationState) {
    let vector = parent_child_vector(case);
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let mut state = runtime.initial_state(&vector).unwrap();
    let suffix = case["id"]
        .as_str()
        .unwrap()
        .trim_start_matches("parent-child-");
    let start = json!({
        "inputs": [{
            "input_id": format!("parent-{}", case["id"].as_str().unwrap()),
            "source_entity_id": 1,
            "sequence": 0,
            "command_id": "START",
            "assigned_tick": 0,
            "action_definition_id": format!("GENERATED_PARENT_{suffix}"),
        }],
        "contacts": [],
    });
    (state, _) = runtime.tick(&state, &start).unwrap();
    for tick in 1..=case["child_count"].as_u64().unwrap() {
        let launch = json!({
            "inputs": [{
                "input_id": format!("launch-{}-{tick}", case["id"].as_str().unwrap()),
                "source_entity_id": 1,
                "sequence": tick,
                "command_id": "LAUNCH",
                "assigned_tick": tick,
            }],
            "contacts": [],
        });
        (state, _) = runtime.tick(&state, &launch).unwrap();
    }
    (runtime, state)
}

#[test]
fn independent_shared_generated_parent_child_structures_respect_limits_and_restore() {
    let corpus = corpus();
    for case in corpus["parent_child_cases"].as_array().unwrap() {
        let (_, state) = run_parent_child_case(case);
        let (_, repeated) = run_parent_child_case(case);
        assert_eq!(state, repeated, "{}:repeat", case["id"]);
        assert_eq!(state.digest().unwrap(), repeated.digest().unwrap());
        assert_eq!(
            SimulationState::restore(&state.snapshot().unwrap()).unwrap(),
            state,
            "{}:restore",
            case["id"]
        );
        assert_eq!(
            state.action_instances.len() as u64,
            case["expected_action_count"].as_u64().unwrap(),
            "{}:action-count",
            case["id"]
        );
        let parent = state
            .action_instances
            .iter()
            .find(|action| action.instance_id == 1)
            .unwrap();
        assert_eq!(
            serde_json::to_value(&parent.child_instance_ids).unwrap(),
            case["expected_child_instance_ids"],
            "{}:children",
            case["id"]
        );
        assert_eq!(
            state.next_action_instance_id,
            case["expected_next_action_instance_id"].as_u64().unwrap(),
            "{}:next-id",
            case["id"]
        );
        for child_id in case["expected_child_instance_ids"].as_array().unwrap() {
            let child = state
                .action_instances
                .iter()
                .find(|action| action.instance_id == child_id.as_u64().unwrap())
                .unwrap();
            assert_eq!(child.parent_instance_id, Some(1), "{}:parent", case["id"]);
            assert_eq!(
                child.parent_slot_id.as_deref(),
                case["child_slot_id"].as_str(),
                "{}:slot",
                case["id"]
            );
        }
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
