import copy
import json
from pathlib import Path

import pytest

from pcam_runtime import PCAMError, action_from_document, load_document
from pcam_runtime.vectors import run_vector

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads(
        (ROOT / "tests/vectors/fault-target-runtime.json").read_text(encoding="utf-8")
    )


def test_python_declared_fault_target_matches_shared_vector():
    vector = _vector()
    expected = vector["expected"]
    run = run_vector(vector)
    state = run.final_state
    action = state.action_instances["1"]
    summary = {
        "tick": state.tick,
        "lifecycle": action.lifecycle_state,
        "fault_record": action.fault_record,
        "transition_serial": action.transition_serial,
        "emission_serial": action.emission_serial,
        "registers": action.registers,
        "input_buffer": [entry.__dict__ for entry in action.input_buffer],
        "stamina": state.resource_banks["1"]["STAMINA"],
    }
    assert run.executor.definitions_by_id["DECLARED_FAULT"].definition_hash == expected[
        "definition_hash"
    ]
    assert state.definition_set_hash == expected["definition_set_hash"]
    assert [trace["state_digest"] for trace in run.traces] == expected[
        "tick_state_digests"
    ]
    assert state.state_hash() == expected["final_state_digest"]
    assert summary == expected["summary"]
    assert [
        {
            "selected_transitions": trace["selected_transitions"],
            "emitted": trace["typed_effects_emitted"],
            "reduced": trace["effect_reduction"],
            "faults": trace["faults"],
        }
        for trace in run.traces
    ] == expected["traces"]


def test_python_declared_fault_target_rejects_invalid_definitions():
    vector = _vector()
    for case in vector["definition_fault_cases"]:
        document = copy.deepcopy(vector)
        transition = document["definitions"][0]["transitions"][0]
        if "target_kind" in case:
            transition["target_kind"] = case["target_kind"]
        if case["fault_code"] is None:
            transition.pop("fault_code")
        else:
            transition["fault_code"] = case["fault_code"]
        with pytest.raises(PCAMError) as raised:
            run_vector(document)
        assert raised.value.code.value == "DEFINITION_REJECTED", case["id"]
        assert raised.value.fault.value == case["fault"], case["id"]


def test_schema_document_adapter_preserves_declared_fault_code():
    document = load_document(ROOT / "examples/heavy-strike.action.yaml")
    document["transitions"][0]["target"] = {
        "kind": "FAULT",
        "fault_code": "DECLARED_TRIP",
    }
    definition = action_from_document(document)
    transition = definition.transitions[0]
    assert transition.target_kind == "FAULT"
    assert transition.fault_code == "DECLARED_TRIP"
    assert definition.to_canonical()["transitions"][0]["fault_code"] == "DECLARED_TRIP"
