import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest

from pcam_runtime import (
    ActionDefinition,
    Contact,
    EffectEnvelope,
    FreezeToken,
    HostSnapshot,
    InteractionCandidate,
    InteractionRule,
    NodeDefinition,
    OverflowPolicy,
    PCAMError,
    RuleOperation,
    RetainedRollbackHistory,
    RuntimeProfile,
    SemanticFact,
    TickExecutor,
    TickInput,
    TransitionDefinition,
    apply_i64,
    apply_u64,
    canonical_candidates,
    euclidean_divmod,
    expire_freeze_tokens,
    is_frozen,
    progression_accrual,
    reduce_effects,
    resolve_candidate,
    run_vector,
    scale_ratio,
)

ROOT = Path(__file__).resolve().parents[3]
CORPUS_PATH = ROOT / "tests/generated/core-properties-v1.json"
GENERATOR_PATH = ROOT / "experiments/generate_core_properties.py"


def _corpus():
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


def _load_generator():
    spec = importlib.util.spec_from_file_location("pcam_generate_core_properties", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_rate_case(case):
    definition = ActionDefinition(
        id=f"GENERATED_RATE_{case['id'].removeprefix('rate-')}",
        rate_scale=case["scale"],
        units_per_tick=case["units_per_tick"],
        nodes=(NodeDefinition("RUN"),),
    )
    executor = TickExecutor(
        (definition,), RuntimeProfile(max_quanta_per_action_per_tick=128)
    )
    state = executor.initial_state()
    for tick_index in range(case["warmup_ticks"]):
        inputs = ()
        if tick_index == 0:
            inputs = (
                TickInput(
                    input_id=f"start-{case['id']}",
                    source_entity_id=1,
                    sequence=0,
                    command_id="START",
                    assigned_tick=0,
                    action_definition_id=definition.id,
                ),
            )
        state, _ = executor.tick(state, inputs)

    restored = executor.restore(executor.save(state))
    direct = state
    for _ in range(case["continuation_ticks"]):
        direct, left = executor.tick(direct)
        restored, right = executor.tick(restored)
        assert left["state_digest"] == right["state_digest"]
    assert direct.to_snapshot() == restored.to_snapshot()

    repeated = executor.initial_state()
    for tick_index in range(case["warmup_ticks"] + case["continuation_ticks"]):
        inputs = ()
        if tick_index == 0:
            inputs = (
                TickInput(
                    input_id=f"start-{case['id']}",
                    source_entity_id=1,
                    sequence=0,
                    command_id="START",
                    assigned_tick=0,
                    action_definition_id=definition.id,
                ),
            )
        repeated, _ = executor.tick(repeated, inputs)
    assert repeated.state_hash() == direct.state_hash()
    return direct.action_instances["1"]


def _run_definition(definition, ticks, case_id):
    executor = TickExecutor((definition,))
    state = executor.initial_state()
    for tick_index in range(ticks):
        inputs = ()
        if tick_index == 0:
            inputs = (
                TickInput(
                    input_id=f"start-{case_id}",
                    source_entity_id=1,
                    sequence=0,
                    command_id="START",
                    assigned_tick=0,
                    action_definition_id=definition.id,
                ),
            )
        state, _ = executor.tick(state, inputs)
    return state


def _reduced_record(effect):
    return {
        "target_entity_id": effect.target_entity_id,
        "effect_type": effect.effect_type,
        "reducer": effect.reducer,
        "value": effect.value,
        "source_effect_ids": list(effect.source_effect_ids),
    }


def _rule(value):
    return InteractionRule(
        rule_id=value["rule_id"],
        stage=value["stage"],
        order=value["order"],
        condition=value["condition"],
        operations=tuple(
            RuleOperation(operation["op"], operation.get("data"))
            for operation in value["operations"]
        ),
        stop_stage=value.get("stop_stage", False),
        stop_pipeline=value.get("stop_pipeline", False),
    )


def _rule_summary(case, values):
    decision = resolve_candidate(
        InteractionCandidate(**case["candidate"]),
        SemanticFact("generated-offense", "OFFENSE"),
        {},
        tuple(_rule(value) for value in values),
    )
    return {
        "status": decision.status,
        "decision_tags": list(decision.decision_tags),
        "trace_rule_ids": [entry["rule_id"] for entry in decision.trace],
    }


def test_generated_core_corpus_is_reproducible():
    assert _load_generator().render_corpus() == CORPUS_PATH.read_bytes()


def test_python_shared_generated_rates_repeat_and_restore_exactly():
    for case in _corpus()["rate_restore_cases"]:
        action = _run_rate_case(case)
        assert action.local_step == case["expected_local_step"], case["id"]
        assert action.quantum_accumulator == case["expected_quantum_accumulator"], case["id"]


def test_python_shared_generated_action_graphs_are_repeatable_and_reach_expected_nodes():
    for case in _corpus()["action_graph_cases"]:
        nodes = tuple(NodeDefinition(f"N{index}") for index in range(case["node_count"]))
        transitions = tuple(
            TransitionDefinition(
                id=f"T{index}",
                source_node=f"N{index}",
                evaluation_point="AFTER_QUANTUM",
                priority=10,
                target_node=f"N{index + 1}",
            )
            for index in range(case["node_count"] - 1)
        )
        definition = ActionDefinition(
            id=f"GENERATED_GRAPH_{case['id'].removeprefix('graph-')}",
            rate_scale=1,
            units_per_tick=1,
            nodes=nodes,
            transitions=transitions,
        )
        first = _run_definition(definition, case["ticks"], case["id"])
        second = _run_definition(definition, case["ticks"], case["id"])
        assert first.to_snapshot() == second.to_snapshot(), case["id"]
        assert first.state_hash() == second.state_hash(), case["id"]
        action = first.action_instances["1"]
        assert action.current_node_id == case["expected_node"], case["id"]
        assert action.local_step == case["expected_local_step"], case["id"]
        assert action.node_step == case["expected_node_step"], case["id"]
        assert action.transition_serial == case["expected_transition_serial"], case["id"]


def test_python_shared_generated_transition_guards_repeat_and_fire():
    for case in _corpus()["transition_guard_cases"]:
        definition = ActionDefinition(
            id=f"GENERATED_GUARD_{case['id'].removeprefix('guard-')}",
            rate_scale=1,
            units_per_tick=1,
            nodes=(NodeDefinition("RUN"), NodeDefinition("DONE")),
            transitions=(
                TransitionDefinition(
                    "guarded",
                    "RUN",
                    "POST_ADVANCE",
                    10,
                    target_node="DONE",
                    guard_expression={
                        "op": "gte",
                        "args": [
                            {"ref": "action.node_step"},
                            {"literal": case["threshold"]},
                        ],
                    },
                ),
            ),
        )
        first = _run_definition(definition, case["ticks"], case["id"])
        second = _run_definition(definition, case["ticks"], case["id"])
        assert first.to_snapshot() == second.to_snapshot(), case["id"]
        action = first.action_instances["1"]
        assert action.current_node_id == case["expected_node"], case["id"]
        assert action.transition_serial == case["expected_transition_serial"], case["id"]


def test_python_shared_generated_input_orders_produce_one_buffer_snapshot():
    for case in _corpus()["input_order_cases"]:
        definition = ActionDefinition(
            id=f"GENERATED_INPUT_{case['id'].removeprefix('input-order-')}",
            rate_scale=1,
            units_per_tick=0,
            nodes=(NodeDefinition("RUN"),),
            buffer_capacity=8,
            default_buffer_lifetime=3,
        )
        executor = TickExecutor((definition,))
        states = []
        for values in (
            case["inputs"],
            case["shuffled_inputs"],
            list(reversed(case["inputs"])),
        ):
            state = executor.initial_state()
            state, _ = executor.tick(
                state,
                (
                    TickInput(
                        input_id=f"start-{case['id']}",
                        source_entity_id=1,
                        sequence=0,
                        command_id="START",
                        assigned_tick=0,
                        action_definition_id=definition.id,
                    ),
                ),
            )
            state, _ = executor.tick(state, tuple(TickInput(**value) for value in values))
            states.append(state)
        assert states[0].to_snapshot() == states[1].to_snapshot() == states[2].to_snapshot()
        entries = states[0].action_instances["1"].input_buffer
        assert [entry.input_id for entry in entries] == case["expected_input_ids"], case["id"]
        assert all(entry.remaining_eligibility_ticks == 2 for entry in entries), case["id"]


def _cross_stage_document(case, order):
    document = json.loads((ROOT / "tests/vectors/pre-stage-arbitration.json").read_text())
    document.pop("cases")
    document["id"] = case["id"]
    document["runtime_profile"]["id"] = f"pcam.generated.{case['id']}.v1"
    document["definitions"][0]["transitions"][0]["priority"] = case[
        "transition_priority"
    ]
    for definition in document["definitions"][1:]:
        definition["start_claims"][0]["amount"] = case["claim_amount"]
    document["initial_state"]["resource_banks"]["1"]["STAMINA"] = case[
        "claim_amount"
    ]
    inputs = {item["input_id"]: item for item in document["ticks"][1]["inputs"]}
    document["ticks"][1]["inputs"] = [inputs[input_id] for input_id in order]
    return document


def test_python_shared_generated_cross_stage_arbitration_is_atomic_and_permutation_invariant():
    for case in _corpus()["cross_stage_arbitration_cases"]:
        runs = []
        for order in (case["input_order"], list(reversed(case["input_order"]))):
            run = run_vector(_cross_stage_document(case, order))
            runs.append(run)
            state = run.final_state
            assert len(state.action_instances) == 2, case["id"]
            assert state.action_instances["1"].transition_serial == case[
                "expected_transition_serial"
            ], case["id"]
            assert state.resource_banks["1"]["STAMINA"] == 0, case["id"]
            assert state.action_slots["1"]["FULL_BODY"] == {
                "capacity": 1,
                "instance_ids": [2],
                "usage": 1,
            }, case["id"]
            winner_hash = run.executor.definitions_by_id[case["expected_winner"]].definition_hash
            assert state.action_instances["2"].definition_hash == winner_hash, case["id"]
            assert run.executor.restore(run.executor.save(state)) == state
        assert runs[0].final_state.to_snapshot() == runs[1].final_state.to_snapshot(), case[
            "id"
        ]
        assert runs[0].final_state.state_hash() == runs[1].final_state.state_hash(), case[
            "id"
        ]


def _interaction_pipeline_document(case, order):
    document = json.loads((ROOT / "tests/vectors/interaction-runtime.json").read_text())
    document.pop("cases")
    document["id"] = case["id"]
    document["runtime_profile"]["id"] = f"pcam.generated.{case['id']}.v1"
    templates = document["definitions"][0]["semantic_facts"][0]["fact"][
        "effect_templates"
    ]
    templates[0]["payload"] = case["damage"]
    templates[1]["payload"] = case["stagger"]
    document["definitions"][1]["semantic_facts"][0]["fact"]["tags"] = (
        [] if case["mode"] == "PLAIN" else [case["mode"]]
    )
    document["initial_state"]["resource_banks"]["2"] = case["initial_resources"]
    base_contact = document["ticks"][0]["contacts"][0]
    contacts = {
        candidate_id: {
            **base_contact,
            "candidate_id": candidate_id,
            "contact_id": "a" if candidate_id == "c1" else "b",
        }
        for candidate_id in ("c1", "c2")
    }
    document["ticks"][0]["contacts"] = [
        contacts[candidate_id] for candidate_id in order
    ]
    return document


def test_python_shared_generated_interaction_pipeline_is_typed_atomic_and_permutation_invariant():
    for case in _corpus()["interaction_pipeline_cases"]:
        runs = []
        for order in (case["contact_order"], list(reversed(case["contact_order"]))):
            run = run_vector(_interaction_pipeline_document(case, order))
            runs.append(run)
            state = run.final_state
            trace = run.traces[0]
            decisions = trace["decision_record_mutations"]
            assert trace["candidate_order"] == ["c1", "c2"], case["id"]
            assert len(state.interaction_ledgers) == 1, case["id"]
            assert state.resource_banks["2"] == case["expected_resources"], case["id"]
            assert [
                [effect["effect_class"], effect["payload"]]
                for effect in trace["typed_effects_emitted"]
            ] == case["expected_effects"], case["id"]
            assert decisions[0]["candidate_id"] == "c1", case["id"]
            assert decisions[0]["accepted"] is case["expected_first_accepted"], case[
                "id"
            ]
            assert [item["rule_id"] for item in decisions[0]["rules_fired"]] == case[
                "expected_rule_ids"
            ], case["id"]
            assert decisions[0]["receipt_written"] is True, case["id"]
            assert decisions[1] == {
                "accepted": False,
                "candidate_id": "c2",
                "reason": "ONCE_PER_ACTION_INSTANCE",
            }, case["id"]
            assert run.executor.restore(run.executor.save(state)) == state
        assert runs[0].final_state.to_snapshot() == runs[1].final_state.to_snapshot(), case[
            "id"
        ]
        assert runs[0].final_state.state_hash() == runs[1].final_state.state_hash(), case[
            "id"
        ]


_FAULT_VECTOR_PATHS = {
    "PROGRESSION": "tests/vectors/fault-trigger-runtime.json",
    "INTERACTION": "tests/vectors/interaction-fault-runtime.json",
    "EFFECT": "tests/vectors/effect-fault-runtime.json",
}


def _fault_origin_document(case, reverse_enumeration):
    document = json.loads((ROOT / _FAULT_VECTOR_PATHS[case["origin"]]).read_text())
    document.pop("cases")
    document["id"] = case["id"]
    document["runtime_profile"]["id"] = f"pcam.generated.{case['id']}.v1"
    document["runtime_profile"]["fault_policy"] = case["policy"]
    if reverse_enumeration:
        document["ticks"][0]["inputs"].reverse()
        document["fault_tick"]["contacts"].reverse()
    if case["origin"] == "PROGRESSION":
        document["runtime_profile"]["limits"]["max_quanta_per_action_per_tick"] = case[
            "parameter"
        ]
        document["rate_overrides"] = {
            "1": case["safe_rate"],
            "2": case["parameter"] + 1,
            "3": 0,
        }
    elif case["origin"] == "INTERACTION":
        document["runtime_profile"]["limits"]["max_redirects_per_candidate"] = case[
            "parameter"
        ]
    else:
        document["definitions"][0]["semantic_facts"][0]["fact"]["effect_templates"][0][
            "payload"
        ] = (1 << 63) - 1 - case["parameter"]
        document["initial_state"]["resource_banks"]["2"]["hp"] = case["initial_hp"]
    return document


def _fault_host(document):
    return HostSnapshot(
        contacts=tuple(
            Contact(
                candidate_id=item["candidate_id"],
                source_instance_id=item["source_instance_id"],
                source_entity_id=item["source_entity_id"],
                target_entity_id=item["target_entity_id"],
                fact_id=item["fact_id"],
                contact_id=item["contact_id"],
            )
            for item in document["fault_tick"]["contacts"]
        )
    )


def _fault_before(document):
    run = run_vector(document)
    state = run.final_state
    if document["id"].startswith("fault-origin-progression"):
        state = replace(
            state,
            action_instances={
                key: replace(action, current_rate_units=document["rate_overrides"][key])
                for key, action in state.action_instances.items()
            },
        )
    return run.executor, state


def test_python_shared_generated_fault_origins_are_atomic_scoped_and_permutation_invariant():
    for case in _corpus()["fault_origin_cases"]:
        pre_fault_snapshots = []
        outcomes = []
        enumeration_values = (
            case["reverse_enumeration"],
            not case["reverse_enumeration"],
        )
        for reverse_enumeration in enumeration_values:
            document = _fault_origin_document(case, reverse_enumeration)
            executor, before = _fault_before(document)
            pre_fault_snapshots.append(before.to_snapshot())
            host = _fault_host(document)
            if case["policy"] == "ABORT_SIMULATION":
                with pytest.raises(PCAMError) as raised:
                    executor.tick(before, (), host)
                assert raised.value.fault.value == case["expected_fault"], case["id"]
                assert raised.value.action_instance_id == case[
                    "expected_fault_action_id"
                ], case["id"]
                assert raised.value.owner_entity_id == case[
                    "expected_owner_entity_id"
                ], case["id"]
                assert before.to_snapshot() == pre_fault_snapshots[-1], case["id"]
                outcomes.append(
                    (
                        raised.value.fault.value,
                        raised.value.action_instance_id,
                        raised.value.owner_entity_id,
                    )
                )
                continue

            state, trace = executor.tick(before, (), host)
            faulted_ids = sorted(
                int(identifier)
                for identifier, action in state.action_instances.items()
                if action.lifecycle_state == "FAULTED"
            )
            entity_fault_owners = sorted(
                int(identifier)
                for identifier, record in state.entity_records.items()
                if "fault_record" in record
            )
            assert state.tick == before.tick + 1, case["id"]
            assert faulted_ids == case["expected_faulted_ids"], case["id"]
            assert entity_fault_owners == case["expected_entity_fault_owners"], case[
                "id"
            ]
            assert all(
                action.fault_record == case["expected_fault"]
                for action in state.action_instances.values()
                if action.lifecycle_state == "FAULTED"
            ), case["id"]
            assert trace["faults"][0]["fault"] == case["expected_fault"], case["id"]
            assert trace["faults"][0]["policy"] == case["policy"], case["id"]
            assert trace["faults"][0]["action_instance_id"] == case[
                "expected_fault_action_id"
            ], case["id"]
            assert trace["faults"][0]["owner_entity_id"] == case[
                "expected_owner_entity_id"
            ], case["id"]
            assert trace["typed_effects_emitted"] == [], case["id"]
            assert state.interaction_ledgers == before.interaction_ledgers, case["id"]
            assert state.resource_banks == before.resource_banks, case["id"]
            assert executor.restore(executor.save(state)) == state
            outcomes.append(state)
        assert pre_fault_snapshots[0] == pre_fault_snapshots[1], case["id"]
        if case["policy"] == "ABORT_SIMULATION":
            assert outcomes[0] == outcomes[1], case["id"]
        else:
            assert outcomes[0].to_snapshot() == outcomes[1].to_snapshot(), case["id"]
            assert outcomes[0].state_hash() == outcomes[1].state_hash(), case["id"]


def _freeze_tokens(values):
    return tuple(
        FreezeToken(
            token_id=value["token_id"],
            source_id=value["source_id"],
            target_id=value["target_id"],
            activation_tick=value["activation_tick"],
            remaining_ticks=value["remaining_ticks"],
            domains=tuple(value["domains"]),
            accrual_policy=value["accrual_policy"],
            stack_group=value["stack_group"],
            stack_policy=value["stack_policy"],
            metadata=value["metadata"],
        )
        for value in values
    )


def _freeze_remaining(tokens):
    return [
        {"token_id": token.token_id, "remaining_ticks": token.remaining_ticks}
        for token in sorted(tokens, key=lambda token: token.token_id)
    ]


def test_python_shared_generated_freeze_token_combinations_match_timing_and_domains():
    domains = ("BUFFER_EXPIRY", "INPUT_CAPTURE", "PROGRESSION")
    for case in _corpus()["freeze_token_cases"]:
        runs = []
        for field in ("tokens", "shuffled_tokens"):
            tokens = _freeze_tokens(case[field])
            observations = []
            for expected in case["expected_ticks"]:
                tick = expected["tick"]
                targets = {}
                for target_id in (1, 2):
                    targets[str(target_id)] = {
                        "domains": {
                            domain: is_frozen(tokens, tick, target_id, domain)
                            for domain in domains
                        },
                        "progression_accrual": progression_accrual(
                            tokens, tick, target_id
                        ),
                    }
                tokens = expire_freeze_tokens(tokens, tick)
                observations.append(
                    {
                        "tick": tick,
                        "targets": targets,
                        "remaining_after_tick": _freeze_remaining(tokens),
                    }
                )
            runs.append(observations)
        assert runs[0] == runs[1] == case["expected_ticks"], case["id"]


def _rollback_start_input(case):
    return TickInput(
        input_id=f"start-{case['id']}",
        source_entity_id=1,
        sequence=0,
        command_id="START",
        assigned_tick=case["corrected_tick"],
        action_definition_id=f"GENERATED_ROLLBACK_{case['id'].removeprefix('rollback-correction-')}",
    )


def test_python_shared_generated_rollback_corrections_match_direct_execution():
    for case in _corpus()["rollback_correction_cases"]:
        definition = ActionDefinition(
            id=f"GENERATED_ROLLBACK_{case['id'].removeprefix('rollback-correction-')}",
            rate_scale=case["scale"],
            units_per_tick=case["units_per_tick"],
            nodes=(NodeDefinition("RUN"),),
        )
        executor = TickExecutor(
            (definition,), RuntimeProfile(max_quanta_per_action_per_tick=16)
        )
        initial = executor.initial_state()
        start_input = _rollback_start_input(case)
        predicted = RetainedRollbackHistory(executor, case["total_ticks"] + 1)
        predicted_state = initial
        direct_state = initial
        for tick in range(case["total_ticks"]):
            predicted_inputs = (
                (start_input,)
                if tick == case["corrected_tick"] and case["predicted_has_start"]
                else ()
            )
            corrected_inputs = (
                (start_input,)
                if tick == case["corrected_tick"] and case["corrected_has_start"]
                else ()
            )
            predicted_state, _, _ = predicted.advance(predicted_state, predicted_inputs)
            direct_state, _ = executor.tick(direct_state, corrected_inputs)
        corrected_inputs = (start_input,) if case["corrected_has_start"] else ()
        correction = predicted.correct_and_resimulate(
            case["corrected_tick"], corrected_inputs
        )
        assert correction.state.to_snapshot() == direct_state.to_snapshot(), case["id"]
        assert correction.rewind_ticks == case["expected_rewind_ticks"], case["id"]
        actions = tuple(correction.state.action_instances.values())
        assert len(actions) == case["expected_action_count"], case["id"]
        if actions:
            assert actions[0].local_step == case["expected_local_step"], case["id"]
            assert (
                actions[0].quantum_accumulator
                == case["expected_quantum_accumulator"]
            ), case["id"]


def _parent_child_definitions(case):
    suffix = case["id"].removeprefix("parent-child-")
    child = ActionDefinition(
        id=f"GENERATED_CHILD_{suffix}",
        rate_scale=1,
        units_per_tick=0,
        nodes=(NodeDefinition("RUN"),),
    )
    parent = ActionDefinition(
        id=f"GENERATED_PARENT_{suffix}",
        rate_scale=1,
        units_per_tick=0,
        nodes=(NodeDefinition("RUN"),),
        child_slot_capacities={case["child_slot_id"]: case["capacity"]},
        child_termination_policies={case["child_slot_id"]: "TERMINATE_CHILD"},
        transitions=(
            TransitionDefinition(
                "launch",
                "RUN",
                "PRE_ADVANCE",
                10,
                target_kind="CHILD_ACTION",
                target_action=child.id,
                child_slot_id=case["child_slot_id"],
                parent_policy="CONTINUE",
                input_command="LAUNCH",
            ),
        ),
    )
    return parent, child


def _run_parent_child_case(case):
    parent, child = _parent_child_definitions(case)
    executor = TickExecutor(
        (parent, child),
        RuntimeProfile(max_children_per_action=case["capacity"]),
    )
    state = executor.initial_state()
    state, _ = executor.tick(
        state,
        (
            TickInput(
                input_id=f"parent-{case['id']}",
                source_entity_id=1,
                sequence=0,
                command_id="START",
                assigned_tick=0,
                action_definition_id=parent.id,
            ),
        ),
    )
    for tick in range(1, case["child_count"] + 1):
        state, _ = executor.tick(
            state,
            (
                TickInput(
                    input_id=f"launch-{case['id']}-{tick}",
                    source_entity_id=1,
                    sequence=tick,
                    command_id="LAUNCH",
                    assigned_tick=tick,
                ),
            ),
        )
    return executor, state


def test_python_shared_generated_parent_child_structures_respect_limits_and_restore():
    for case in _corpus()["parent_child_cases"]:
        executor, state = _run_parent_child_case(case)
        _, repeated = _run_parent_child_case(case)
        assert state.to_snapshot() == repeated.to_snapshot(), case["id"]
        assert state.state_hash() == repeated.state_hash(), case["id"]
        assert executor.restore(executor.save(state)).to_snapshot() == state.to_snapshot()
        assert len(state.action_instances) == case["expected_action_count"], case["id"]
        parent = state.action_instances["1"]
        assert list(parent.child_instance_ids) == case["expected_child_instance_ids"], case["id"]
        assert state.next_action_instance_id == case["expected_next_action_instance_id"]
        for child_id in case["expected_child_instance_ids"]:
            child = state.action_instances[str(child_id)]
            assert (child.parent_instance_id, child.parent_slot_id) == (
                1,
                case["child_slot_id"],
            ), case["id"]


def test_python_shared_generated_numeric_division_is_euclidean():
    for case in _corpus()["numeric_division_cases"]:
        assert euclidean_divmod(case["dividend"], case["divisor"]) == (
            case["quotient"],
            case["remainder"],
        ), case["id"]


def test_python_shared_generated_numeric_ratios_use_checked_floor_rounding():
    for case in _corpus()["numeric_ratio_cases"]:
        assert (
            scale_ratio(case["value"], case["numerator"], case["denominator"])
            == case["result"]
        ), case["id"]


def test_python_shared_generated_numeric_overflow_policies_match():
    policies = {
        "FAULT": OverflowPolicy.FAULT,
        "SATURATE": OverflowPolicy.SATURATE,
        "WRAP": OverflowPolicy.WRAP,
    }
    functions = {"I64": apply_i64, "U64": apply_u64}
    for case in _corpus()["numeric_overflow_cases"]:
        operation = functions[case["domain"]]
        if case["fault"]:
            with pytest.raises(PCAMError) as raised:
                operation(int(case["input"]), policies[case["policy"]])
            assert raised.value.fault.value == case["fault"], case["id"]
        else:
            assert (
                operation(int(case["input"]), policies[case["policy"]])
                == case["result"]
            ), case["id"]


def test_python_shared_generated_effect_aggregation_is_permutation_invariant():
    for case in _corpus()["effect_aggregation_cases"]:
        results = []
        for field in ("effects", "shuffled_effects"):
            reduced, rejected = reduce_effects(
                tuple(EffectEnvelope(**value) for value in case[field])
            )
            assert rejected == ()
            assert len(reduced) == 1
            results.append(_reduced_record(reduced[0]))
        assert results[0] == results[1] == case["expected"], case["id"]


def test_python_shared_generated_candidate_permutations_have_one_canonical_order():
    for case in _corpus()["candidate_permutation_cases"]:
        candidates = tuple(InteractionCandidate(**value) for value in case["candidates"])
        reversed_candidates = tuple(reversed(candidates))
        expected = case["expected_candidate_ids"]
        assert [item.candidate_id for item in canonical_candidates(candidates)] == expected
        assert [item.candidate_id for item in canonical_candidates(reversed_candidates)] == expected


def test_python_shared_generated_rule_sets_ignore_definition_enumeration():
    for case in _corpus()["interaction_rule_cases"]:
        expected = {
            "status": "ACCEPTED",
            "decision_tags": case["expected_decision_tags"],
            "trace_rule_ids": case["expected_trace_rule_ids"],
        }
        assert _rule_summary(case, case["rules"]) == expected, case["id"]
        assert _rule_summary(case, case["shuffled_rules"]) == expected, case["id"]
