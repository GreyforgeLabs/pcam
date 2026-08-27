from pathlib import Path

from copy import deepcopy
import json

from pcam_runtime import (
    TickExecutor,
    TickInput,
    action_from_document,
    compile_pcam24,
    load_document,
    validate_document,
)

ROOT = Path(__file__).resolve().parents[3]
VECTOR = json.loads((ROOT / "tests/vectors/pcam24-lifecycle.json").read_text())


def test_pcam24_compiles_to_valid_core_action_with_explicit_lifecycle():
    source = load_document(ROOT / "tests" / "valid" / "minimal-pcam24.json")
    compiled = compile_pcam24(source)
    assert compiled["kind"] == "action"
    assert compiled["nodes"]["timeline"]["duration_quanta"] == 24
    assert compiled["transitions"][0]["target"] == {"kind": "TERMINATE"}
    assert validate_document(compiled) == []


def test_pcam24_loop_compiles_explicit_cycle_boundary():
    source = load_document(ROOT / "tests" / "valid" / "minimal-pcam24.json")
    source["lifecycle"] = "LOOP"
    compiled = compile_pcam24(source)
    transition = compiled["transitions"][0]
    assert transition["cycle_delta"] == 1
    assert transition["target"] == {"kind": "NODE", "node": "timeline", "target_step": 0}


def test_pcam24_clamp_compiles_to_timeline_cell_23_with_progression_held():
    source = load_document(ROOT / "tests" / "valid" / "minimal-pcam24.json")
    source["lifecycle"] = "CLAMP"
    compiled = compile_pcam24(source)
    transition = compiled["transitions"][0]
    assert tuple(compiled["nodes"]) == ("timeline",)
    assert transition["target"] == {"kind": "NODE", "node": "timeline", "target_step": 23}
    assert transition["assignments"] == [
        {"target": "action.current_rate_units", "value": {"literal": 0}}
    ]
    assert compiled["profiles"]["pcam24"]["projection"] == [
        {"node": "timeline", "step_range": [0, 24], "phase_range": [0, 24]}
    ]
    assert validate_document(compiled) == []


def _execute_lifecycle(lifecycle):
    source = deepcopy(VECTOR["source"])
    source["lifecycle"] = lifecycle
    compiled = compile_pcam24(source)
    executor = TickExecutor((action_from_document(compiled),))
    state = executor.initial_state()
    start = TickInput(
        "start",
        7,
        0,
        "START",
        0,
        action_definition_id=source["id"],
    )
    for tick in range(24):
        state, _ = executor.tick(state, (start,) if tick == 0 else ())
    return compiled, executor, state


def _projection(action):
    return {
        key: getattr(action, key)
        for key in VECTOR["cases"][0]["expected_projection"]
    }


def test_pcam24_lifecycle_execution_and_projection_state_are_explicit():
    for case in VECTOR["cases"]:
        compiled, executor, state = _execute_lifecycle(case["lifecycle"])
        transition = compiled["transitions"][0]
        assert transition["target"] == case["compiled_target"]
        assert transition["assignments"] == case["compiled_assignments"]
        assert transition["cycle_delta"] == case["compiled_cycle_delta"]
        action = state.action_instances["1"]
        assert _projection(action) == case["expected_projection"]
        assert executor.restore(executor.save(state)) == state
        if case["lifecycle"] == "CLAMP":
            clamped_again, _ = executor.tick(state)
            assert clamped_again.action_instances["1"] == action
