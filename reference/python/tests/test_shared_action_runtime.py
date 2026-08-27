import json
from dataclasses import replace
from pathlib import Path

import pytest

from pcam_runtime import (
    ActionDefinition,
    canonical_hash,
    FreezeToken,
    NodeDefinition,
    PCAMError,
    PredicateDefinition,
    RuntimeProfile,
    TickExecutor,
    TickInput,
    TransitionDefinition,
)

ROOT = Path(__file__).resolve().parents[3]


def _definition(raw):
    return ActionDefinition(
        id=raw["id"],
        rate_scale=raw["rate"]["scale"],
        units_per_tick=raw["rate"]["units_per_tick"],
        initial_node_id=raw["initial_node"],
        buffer_capacity=raw.get("buffer_capacity", 8),
        buffer_overflow_policy=raw.get("buffer_overflow_policy", "DROP_OLDEST"),
        default_buffer_lifetime=raw.get("default_buffer_lifetime", 1),
        nodes=tuple(NodeDefinition(**node) for node in raw["nodes"]),
        predicates=tuple(PredicateDefinition(**predicate) for predicate in raw.get("predicates", ())),
        transitions=tuple(TransitionDefinition(**transition) for transition in raw["transitions"]),
    )


def _profile(raw):
    return RuntimeProfile(
        max_quanta_per_action_per_tick=raw["max_quanta_per_action_per_tick"],
        max_internal_transitions_per_action_per_tick=raw["max_internal_transitions_per_tick"],
    )


def _projection(action):
    return {
        "owner_entity_id": action.owner_entity_id,
        "lifecycle_state": action.lifecycle_state,
        "current_node_id": action.current_node_id,
        "node_step": action.node_step,
        "local_step": action.local_step,
        "cycle": action.cycle,
        "transition_serial": action.transition_serial,
        "quantum_accumulator": action.quantum_accumulator,
        "deferred_quanta": action.deferred_quanta,
        "current_rate_units": action.current_rate_units,
        "predicate_truth_state": action.predicate_truth_state,
        "predicate_entry_serials": action.predicate_entry_serials,
        "predicate_exit_serials": action.predicate_exit_serials,
        "input_buffer": [entry.__dict__ for entry in action.input_buffer],
        "fault_record": action.fault_record,
    }


def _vectors():
    return json.loads((ROOT / "tests/vectors/action-runtime.json").read_text(encoding="utf-8"))


def _apply_freezes(state, directive, tick_index):
    domains = []
    if directive.get("progression"):
        domains.append("PROGRESSION")
    if directive.get("pre_advance_transitions"):
        domains.append("PRE_ADVANCE_TRANSITIONS")
    if directive.get("post_advance_transitions"):
        domains.append("POST_ADVANCE_TRANSITIONS")
    if directive.get("input_capture"):
        domains.append("INPUT_CAPTURE")
    if directive.get("buffer_expiry"):
        domains.append("BUFFER_EXPIRY")
    if not domains:
        return replace(state, freeze_tokens=())
    token = FreezeToken.created(
        token_id=1000 + tick_index,
        source_id=99,
        target_id=1,
        creation_tick=tick_index - 1,
        duration=1,
        domains=tuple(domains),
        accrual_policy=directive.get("progression", "HOLD"),
    )
    return replace(state, freeze_tokens=(token,))


def test_python_runtime_matches_shared_progression_and_transition_vectors():
    vectors = _vectors()
    for case in vectors["cases"]:
        definition = _definition(case["definition"])
        executor = TickExecutor((definition,), profile=_profile(vectors["limits"]))
        state = executor.initial_state()
        for tick_index, expected in enumerate(case["expected"]):
            state = _apply_freezes(state, case.get("freezes", [{}] * case["ticks"])[tick_index], tick_index)
            inputs = tuple(TickInput(**item) for item in case.get("inputs", [])[tick_index]) if case.get("inputs") else ()
            if tick_index == 0:
                inputs = (*inputs,
                    TickInput(
                        input_id=f"start-{case['id']}",
                        source_entity_id=1,
                        sequence=0,
                        command_id="START",
                        assigned_tick=0,
                        action_definition_id=definition.id,
                    )
                )
            state, _ = executor.tick(state, inputs)
            actual = _projection(state.action_instances["1"])
            assert {key: actual[key] for key in expected} == expected, case["id"]
        assert canonical_hash(actual) == case["final_state_sha256"], case["id"]
        restored = executor.restore(executor.save(state))
        assert _projection(restored.action_instances["1"]) == actual, case["id"]
        restored, _ = executor.tick(restored)
        assert canonical_hash(_projection(restored.action_instances["1"])) == case["continuation_state_sha256"], case["id"]


def test_python_runtime_matches_shared_limit_faults():
    for case in _vectors()["fault_cases"]:
        definition = _definition(case["definition"])
        executor = TickExecutor((definition,), profile=_profile(case["limits"]))
        state = executor.initial_state()
        start_input = TickInput(
            input_id=f"start-{case['id']}",
            source_entity_id=1,
            sequence=0,
            command_id="START",
            assigned_tick=0,
            action_definition_id=definition.id,
        )
        with pytest.raises(PCAMError) as raised:
            for tick_index in range(case.get("fault_tick", 0) + 1):
                inputs = tuple(TickInput(**item) for item in case.get("inputs", [])[tick_index]) if case.get("inputs") else ()
                if tick_index == 0:
                    inputs = (*inputs, start_input)
                state, _ = executor.tick(state, inputs)
        assert raised.value.fault.value == case["fault"], case["id"]


def test_python_runtime_rejects_shared_invalid_definitions():
    for case in _vectors()["definition_fault_cases"]:
        with pytest.raises(PCAMError):
            TickExecutor((_definition(case["definition"]),))
