from copy import deepcopy
from pathlib import Path

from pcam_runtime import TickExecutor, TickInput, action_from_document, load_document


ROOT = Path(__file__).resolve().parents[3]


def _document():
    document = deepcopy(load_document(ROOT / "tests/valid/minimal-action.json"))
    document["id"] = "greyforge.test.parameters"
    document["parameters"] = {
        "damage": {
            "type": "I64",
            "required": True,
            "minimum": 0,
            "maximum": 100,
            "capture_policy": "CAPTURE_ON_START",
        },
        "tags": {
            "type": "BOUNDED_LIST",
            "required": False,
            "default": [],
            "capacity": 4,
            "capture_policy": "CAPTURE_ON_START",
        }
    }
    document["nodes"]["done"]["entry_effects"] = [
        {
            "effect_type": "presentation.damage",
            "authoritative": False,
            "payload": {"ref": "action.parameter.damage"},
        }
    ]
    return document


def _start(parameters):
    return TickInput(
        "start",
        3,
        0,
        "START",
        0,
        payload={"parameters": parameters},
        action_definition_id="greyforge.test.parameters",
    )


def test_direct_start_validates_and_captures_supplied_parameters():
    executor = TickExecutor((action_from_document(_document()),))
    tags = ["heavy", "grounded"]

    state, trace = executor.tick(
        executor.initial_state(),
        (_start({"damage": 17, "tags": tags}),),
    )
    tags.append("mutated-after-capture")

    assert state.action_instances["1"].captured_parameters == {
        "damage": 17,
        "tags": ("heavy", "grounded"),
    }
    assert trace["typed_effects_emitted"][0]["payload"] == 17
    assert executor.restore(executor.save(state)) == state


def test_missing_unknown_and_out_of_bounds_parameters_fail_before_allocation():
    executor = TickExecutor((action_from_document(_document()),))
    for parameters, expected_fault in (
        ({}, "MISSING_REFERENCE"),
        ({"damage": 1, "unknown": 2}, "MISSING_REFERENCE"),
        ({"damage": 101}, "INTEGER_OVERFLOW"),
    ):
        initial = executor.initial_state()
        state, _, error = executor.tick_with_fault_trace(initial, (_start(parameters),))
        assert error is not None
        assert error.code.value == "INVALID_INPUT"
        assert error.fault.value == expected_fault
        assert state == initial
        assert state.next_action_instance_id == 1
