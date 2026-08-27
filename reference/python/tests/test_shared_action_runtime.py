import json
from pathlib import Path

import pytest

from pcam_runtime import (
    ActionDefinition,
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
        "lifecycle_state": action.lifecycle_state,
        "current_node_id": action.current_node_id,
        "node_step": action.node_step,
        "local_step": action.local_step,
        "transition_serial": action.transition_serial,
        "quantum_accumulator": action.quantum_accumulator,
        "predicate_truth_state": action.predicate_truth_state,
        "predicate_entry_serials": action.predicate_entry_serials,
        "predicate_exit_serials": action.predicate_exit_serials,
    }


def _vectors():
    return json.loads((ROOT / "tests/vectors/action-runtime.json").read_text(encoding="utf-8"))


def test_python_runtime_matches_shared_progression_and_transition_vectors():
    vectors = _vectors()
    for case in vectors["cases"]:
        definition = _definition(case["definition"])
        executor = TickExecutor((definition,), profile=_profile(vectors["limits"]))
        state = executor.initial_state()
        for tick_index, expected in enumerate(case["expected"]):
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
            actual = _projection(state.action_instances["1"])
            assert {key: actual[key] for key in expected} == expected, case["id"]


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
            executor.tick(state, (start_input,))
        assert raised.value.fault.value == case["fault"], case["id"]


def test_python_runtime_rejects_shared_invalid_definitions():
    for case in _vectors()["definition_fault_cases"]:
        with pytest.raises(PCAMError):
            TickExecutor((_definition(case["definition"]),))
