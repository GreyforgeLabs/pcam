from copy import deepcopy
from pathlib import Path

from pcam_runtime import (
    ActionDefinition,
    Assignment,
    DefinitionEffect,
    NodeDefinition,
    TickExecutor,
    TickInput,
    TransitionDefinition,
    action_from_document,
    load_document,
    validate_document,
)


ROOT = Path(__file__).resolve().parents[3]


def _base_document():
    document = deepcopy(load_document(ROOT / "tests/valid/minimal-action.json"))
    document["id"] = "greyforge.test.operations"
    document["rate"] = {"scale": 1, "units_per_tick": 1}
    document["registers"] = {
        "counter": {
            "type": "U64",
            "initial": 0,
            "minimum": 0,
            "maximum": 100,
            "overflow": "FAULT",
            "serialization_policy": "AUTHORITATIVE",
        }
    }
    return document


def _assignment(amount):
    return {
        "target": "action.register.counter",
        "value": {
            "op": "add",
            "args": [
                {"ref": "action.register.counter"},
                {"literal": amount},
            ],
        },
    }


def _presentation(effect_type):
    return {
        "effect_type": effect_type,
        "authoritative": False,
        "payload": {"ref": "action.register.counter"},
    }


def _start(executor):
    return TickInput(
        input_id="start",
        source_entity_id=7,
        sequence=0,
        command_id="START",
        assigned_tick=0,
        action_definition_id="greyforge.test.operations",
    )


def test_document_operations_execute_in_the_normative_mutation_order():
    document = _base_document()
    document["initial_node"] = "source"
    document["nodes"] = {
        "source": {
            "id": "source",
            "mode": "TIMED",
            "duration_quanta": 1,
            "seekable": False,
            "entry_assignments": [],
            "entry_effects": [],
            "exit_assignments": [_assignment(1)],
            "exit_effects": [_presentation("trace.source_exit")],
            "tags": [],
            "extensions": {},
        },
        "target": {
            "id": "target",
            "mode": "TERMINAL",
            "seekable": False,
            "entry_assignments": [_assignment(1)],
            "entry_effects": [_presentation("trace.target_entry")],
            "exit_assignments": [],
            "exit_effects": [],
            "tags": [],
            "extensions": {},
        },
    }
    document["transitions"] = [
        {
            "id": "advance",
            "source_node": "source",
            "evaluation_point": "AFTER_QUANTUM",
            "priority": 1,
            "guard": {"literal": True},
            "target": {"kind": "NODE", "node": "target"},
            "input_match": None,
            "event_match": None,
            "claims": [],
            "consume_policy": "NEVER",
            "exit_assignments": [_assignment(1)],
            "assignments": [_assignment(1)],
            "entry_assignments": [_assignment(1)],
            "effects": [_presentation("trace.transition")],
            "cycle_delta": 2,
            "metadata": {},
        }
    ]
    assert validate_document(document) == []

    executor = TickExecutor((action_from_document(document),))
    state, trace = executor.tick(executor.initial_state(), (_start(executor),))
    action = state.action_instances["1"]

    assert action.registers == {"counter": 5}
    assert action.cycle == 2
    assert action.current_node_id == "target"
    assert action.lifecycle_state == "TERMINATED"
    assert action.transition_serial == 1
    assert action.emission_serial == 3
    assert [effect["payload"] for effect in trace["typed_effects_emitted"]] == [2, 3, 5]
    assert [effect["effect_id"] for effect in trace["typed_effects_emitted"]] == [
        "0:1:0",
        "0:1:1",
        "0:1:2",
    ]


def test_initial_terminal_node_runs_entry_operations_before_termination():
    document = _base_document()
    node = document["nodes"]["done"]
    node["entry_assignments"] = [
        {
            "target": "action.register.counter",
            "value": {"literal": 9},
        }
    ]
    node["entry_effects"] = [_presentation("trace.initial_terminal")]
    assert validate_document(document) == []

    executor = TickExecutor((action_from_document(document),))
    state, trace = executor.tick(executor.initial_state(), (_start(executor),))
    action = state.action_instances["1"]

    assert action.lifecycle_state == "TERMINATED"
    assert action.registers == {"counter": 9}
    assert action.emission_serial == 1
    assert trace["typed_effects_emitted"][0]["payload"] == 9


def test_register_overflow_fault_preserves_the_pre_tick_state():
    document = _base_document()
    document["registers"]["counter"]["maximum"] = 3
    document["nodes"]["done"]["entry_assignments"] = [
        {
            "target": "action.register.counter",
            "value": {"literal": 4},
        }
    ]
    executor = TickExecutor((action_from_document(document),))
    initial = executor.initial_state()

    state, trace, error = executor.tick_with_fault_trace(initial, (_start(executor),))

    assert error is not None
    assert error.fault.value == "INTEGER_OVERFLOW"
    assert state == initial
    assert trace["state_digest"] == initial.state_hash()


def test_validator_rejects_assignment_to_an_undeclared_register():
    document = _base_document()
    document["nodes"]["done"]["entry_assignments"] = [
        {
            "target": "action.register.missing",
            "value": {"literal": 1},
        }
    ]

    diagnostics = validate_document(document)

    assert [(item.code, item.fault, item.path) for item in diagnostics] == [
        (
            "DEFINITION_REJECTED",
            "MISSING_REFERENCE",
            "$.nodes.done.entry_assignments[0].target",
        )
    ]


def test_action_target_keeps_transition_assignments_on_source_and_runs_new_initial_entry():
    increment = Assignment(
        "action.register.counter",
        {
            "op": "add",
            "args": [{"ref": "action.register.counter"}, {"literal": 1}],
        },
    )
    target = ActionDefinition(
        "TARGET",
        1,
        0,
        (
            NodeDefinition(
                "READY",
                entry_assignments=(increment,),
                entry_effects=(
                    DefinitionEffect(
                        "trace.target_start",
                        False,
                        {"ref": "action.register.counter"},
                    ),
                ),
            ),
        ),
        register_initials={"counter": 10},
        register_declarations={
            "counter": {
                "type": "U64",
                "minimum": 0,
                "maximum": 100,
                "overflow": "FAULT",
            }
        },
    )
    source = ActionDefinition(
        "SOURCE",
        1,
        1,
        (
            NodeDefinition(
                "RUN",
                "TIMED",
                1,
                exit_assignments=(increment,),
            ),
        ),
        transitions=(
            TransitionDefinition(
                "replace",
                "RUN",
                "AFTER_QUANTUM",
                1,
                target_kind="ACTION",
                target_action="TARGET",
                entry_assignments=(increment,),
            ),
        ),
        register_initials={"counter": 0},
        register_declarations=target.register_declarations,
    )
    executor = TickExecutor((source, target))
    start = TickInput("start-source", 7, 0, "START", 0, action_definition_id="SOURCE")

    state, trace = executor.tick(executor.initial_state(), (start,))

    assert state.action_instances["1"].lifecycle_state == "TERMINATED"
    assert state.action_instances["1"].registers == {"counter": 2}
    assert state.action_instances["2"].lifecycle_state == "RUNNING"
    assert state.action_instances["2"].registers == {"counter": 11}
    assert [(item["effect_id"], item["payload"]) for item in trace["typed_effects_emitted"]] == [
        ("0:2:0", 11)
    ]


def test_authoritative_node_effect_reduces_and_commits_in_stage_ten():
    document = _base_document()
    document["nodes"]["done"]["entry_effects"] = [
        {
            "effect_type": "combat.damage",
            "effect_class": "DAMAGE",
            "authoritative": True,
            "reducer": "SUM",
            "target": 9,
            "payload": {"literal": 4},
        }
    ]
    executor = TickExecutor((action_from_document(document),))
    initial = executor.initial_state(resource_banks={"9": {"hp": 10}})

    state, trace = executor.tick(initial, (_start(executor),))

    assert state.resource_banks["9"]["hp"] == 6
    assert trace["effect_reduction"] == [
        {
            "effect_type": "combat.damage",
            "reducer": "SUM",
            "source_effect_ids": ["0:1:0"],
            "target_entity_id": 9,
            "value": 4,
        }
    ]
