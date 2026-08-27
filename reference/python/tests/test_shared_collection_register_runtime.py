import copy
import json
from pathlib import Path

from pcam_runtime.vectors import run_vector

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads(
        (ROOT / "tests/vectors/collection-register-runtime.json").read_text(
            encoding="utf-8"
        )
    )


def _registers(action):
    return {key: list(value) for key, value in action.registers.items()}


def test_python_collection_register_assignments_match_shared_vector():
    vector = _vector()
    expected = vector["expected"]
    run = run_vector(vector)
    state = run.final_state
    action = state.action_instances["1"]
    summary = {
        "tick": state.tick,
        "node": action.current_node_id,
        "registers": _registers(action),
        "transition_serial": action.transition_serial,
        "emission_serial": action.emission_serial,
        "input_buffer": [entry.__dict__ for entry in action.input_buffer],
    }
    assert run.executor.definitions_by_id["COLLECTIONS"].definition_hash == expected[
        "definition_hash"
    ]
    assert state.definition_set_hash == expected["definition_set_hash"]
    assert [trace["state_digest"] for trace in run.traces] == expected[
        "tick_state_digests"
    ]
    assert state.state_hash() == expected["final_state_digest"]
    assert summary == expected["summary"]
    assert json.loads(json.dumps(run.traces[-1]["typed_effects_emitted"])) == expected[
        "emitted"
    ]


def test_python_collection_assignment_faults_are_tick_atomic():
    vector = _vector()
    for case in vector["fault_cases"]:
        document = copy.deepcopy(vector)
        document["runtime_profile"]["fault_policy"] = "FAULT_ACTION"
        assignment = document["definitions"][0]["transitions"][0]["assignments"][3]
        assignment["target"] = case["target"]
        assignment["value"] = case["value"]
        run = run_vector(document)
        state = run.final_state
        action = state.action_instances["1"]
        summary = {
            "tick": state.tick,
            "node": action.current_node_id,
            "lifecycle": action.lifecycle_state,
            "fault_record": action.fault_record,
            "registers": _registers(action),
            "transition_serial": action.transition_serial,
            "emission_serial": action.emission_serial,
            "input_buffer": [entry.__dict__ for entry in action.input_buffer],
        }
        assert [trace["state_digest"] for trace in run.traces] == case[
            "tick_state_digests"
        ], case["id"]
        assert state.state_hash() == case["final_state_digest"], case["id"]
        assert summary == vector["expected"]["fault_summary"], case["id"]
        assert run.traces[-1]["faults"][0]["fault"] == case["fault"], case["id"]
        assert run.traces[-1]["typed_effects_emitted"] == [], case["id"]
