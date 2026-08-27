import json
from pathlib import Path

import pytest

from pcam_runtime import PCAMError
from pcam_runtime.vectors import run_vector

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads(
        (ROOT / "tests/vectors/transition-context-runtime.json").read_text(encoding="utf-8")
    )


def _case_document(vector, case):
    document = json.loads(json.dumps(vector))
    declaration = document["definitions"][0]["import_declarations"]["allowed"]
    declaration["failure_policy"] = case["failure_policy"]
    if "default" in case:
        declaration["default"] = case["default"]
    else:
        declaration.pop("default", None)
    document["ticks"][1]["imports"] = case["imports"]
    return document


def test_python_complete_state_transition_context_matches_shared_vectors():
    vector = _vector()
    for case in vector["cases"]:
        document = _case_document(vector, case)
        run = run_vector(document)
        state = run.final_state
        action = state.action_instances["1"]
        summary = {
            "node": action.current_node_id,
            "transition_serial": action.transition_serial,
            "captured_parameters": action.captured_parameters,
            "registers": action.registers,
            "predicate_truth_state": action.predicate_truth_state,
            "predicate_entry_serials": action.predicate_entry_serials,
            "input_buffer": [entry.__dict__ for entry in action.input_buffer],
            "host_imports": state.host_state["imports"],
        }
        assert [trace["state_digest"] for trace in run.traces] == case["tick_state_digests"]
        assert state.state_hash() == case["final_state_digest"], case["id"]
        assert summary == case["expected"], case["id"]


def test_python_transition_context_rejects_invalid_host_imports():
    vector = _vector()
    for case in vector["fault_cases"]:
        with pytest.raises(PCAMError) as raised:
            run_vector(_case_document(vector, case))
        assert raised.value.fault.value == case["fault"], case["id"]


def test_python_ordered_assignment_fault_is_tick_atomic_before_containment():
    vector = _vector()
    for case in vector["assignment_fault_cases"]:
        document = json.loads(json.dumps(vector))
        document["runtime_profile"]["fault_policy"] = "FAULT_ACTION"
        document["definitions"][0]["register_declarations"]["order"]["maximum"] = case[
            "register_maximum"
        ]
        run = run_vector(document)
        state = run.final_state
        action = state.action_instances["1"]
        summary = {
            "tick": state.tick,
            "node": action.current_node_id,
            "lifecycle": action.lifecycle_state,
            "fault_record": action.fault_record,
            "registers": action.registers,
            "input_buffer": [entry.__dict__ for entry in action.input_buffer],
        }
        assert [trace["state_digest"] for trace in run.traces] == case["tick_state_digests"]
        assert state.state_hash() == case["final_state_digest"], case["id"]
        assert run.traces[-1]["faults"][0]["fault"] == case["fault"], case["id"]
        assert summary == case["expected"], case["id"]


def test_python_complete_state_rejects_invalid_predicate_graphs():
    vector = _vector()
    for case in vector["definition_fault_cases"]:
        document = json.loads(json.dumps(vector))
        document["definitions"][0]["predicates"] = case["predicates"]
        with pytest.raises(PCAMError) as raised:
            run_vector(document)
        assert raised.value.code.value == "DEFINITION_REJECTED", case["id"]
        assert raised.value.fault.value == case["fault"], case["id"]


def test_python_complete_state_rejects_invalid_transition_bounds():
    vector = _vector()
    for case in vector["transition_definition_fault_cases"]:
        document = json.loads(json.dumps(vector))
        transition = document["definitions"][0]["transitions"][0]
        target = document["definitions"][0]["nodes"][1]
        for field in ("cycle_delta", "target_step"):
            if field in case:
                transition[field] = case[field]
        if "target_seekable" in case:
            target["seekable"] = case["target_seekable"]
        if "target_mode" in case:
            target["mode"] = case["target_mode"]
            target["duration_quanta"] = case["target_duration_quanta"]
        with pytest.raises(PCAMError) as raised:
            run_vector(document)
        assert raised.value.code.value == "DEFINITION_REJECTED", case["id"]
        assert raised.value.fault.value == case["fault"], case["id"]


def _structural_fault_document(vector, case):
    document = json.loads(json.dumps(vector))
    transition = document["definitions"][0]["transitions"][0]
    mutation = case["mutation"]
    if mutation == "DUPLICATE_PRIORITY":
        duplicate = json.loads(json.dumps(transition))
        duplicate["id"] = "duplicate-context-match"
        document["definitions"][0]["transitions"].append(duplicate)
    elif mutation == "MISSING_SOURCE":
        transition["source_node"] = "MISSING"
    elif mutation == "MISSING_GUARD":
        transition["guard_predicate"] = "MISSING"
    elif mutation == "AFTER_QUANTUM_CLAIM":
        transition["evaluation_point"] = "AFTER_QUANTUM"
        transition["claims"] = [{"kind": "RESOURCE", "key": "STAMINA", "amount": 1}]
    elif mutation == "MISSING_ACTION_TARGET":
        transition["target_kind"] = "ACTION"
        transition["target_action"] = "MISSING"
        transition.pop("target_node", None)
    else:  # pragma: no cover - vector enum is closed by review
        raise AssertionError(mutation)
    return document


def test_python_complete_state_rejects_invalid_transition_structure():
    vector = _vector()
    for case in vector["structural_definition_fault_cases"]:
        with pytest.raises(PCAMError) as raised:
            run_vector(_structural_fault_document(vector, case))
        assert raised.value.code.value == "DEFINITION_REJECTED", case["id"]
        assert raised.value.fault.value == case["fault"], case["id"]
