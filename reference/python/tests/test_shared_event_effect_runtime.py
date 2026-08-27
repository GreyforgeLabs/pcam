import copy
import json
from pathlib import Path

import pytest

from pcam_runtime import HostSnapshot, PCAMError
from pcam_runtime.vectors import run_vector

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads(
        (ROOT / "tests/vectors/event-effect-runtime.json").read_text(encoding="utf-8")
    )


def test_python_event_effect_queues_delivers_and_restores():
    vector = _vector()
    expected = vector["expected"]
    run = run_vector(vector)
    state = run.final_state
    action = state.action_instances["1"]
    summary = {
        "tick": state.tick,
        "node": action.current_node_id,
        "transition_serial": action.transition_serial,
        "pending_events": list(state.pending_events),
        "event_inbox": list(action.event_inbox),
        "input_buffer": [entry.__dict__ for entry in action.input_buffer],
    }
    assert run.executor.definitions_by_id["EVENTER"].definition_hash == expected[
        "definition_hash"
    ]
    assert state.definition_set_hash == expected["definition_set_hash"]
    assert [trace["state_digest"] for trace in run.traces] == expected[
        "tick_state_digests"
    ]
    assert state.state_hash() == expected["final_state_digest"]
    assert [trace["events_delivered"] for trace in run.traces] == expected[
        "events_delivered"
    ]
    assert summary == expected["summary"]
    assert run.traces[1]["effects_emitted"] == expected["emitted"]
    assert run.traces[1]["effect_reduction"] == expected["queue_trace"]

    prefix = copy.deepcopy(vector)
    prefix["ticks"] = prefix["ticks"][:2]
    pending = run_vector(prefix)
    assert list(pending.final_state.pending_events) == expected["pending_after_emission"]
    restored = pending.executor.restore(pending.executor.save(pending.final_state))
    continued, trace = pending.executor.tick(restored, (), HostSnapshot())
    assert trace["events_delivered"] == ["1:1:wake"]
    assert continued.state_hash() == expected["final_state_digest"]


def test_python_event_effect_rejects_invalid_definitions():
    vector = _vector()
    for case in vector["definition_fault_cases"]:
        document = copy.deepcopy(vector)
        effect = document["definitions"][0]["transitions"][1]["effects"][0]
        if "remove" in case:
            effect.pop(case["remove"])
        else:
            effect[case["field"]] = case["value"]
        with pytest.raises(PCAMError) as raised:
            run_vector(document)
        assert raised.value.code.value == "DEFINITION_REJECTED", case["id"]
        assert raised.value.fault.value == case["fault"], case["id"]


def test_python_duplicate_created_event_id_faults_atomically():
    vector = _vector()
    document = copy.deepcopy(vector)
    document["runtime_profile"]["fault_policy"] = "FAULT_ACTION"
    effects = document["definitions"][0]["transitions"][1]["effects"]
    effects.append(copy.deepcopy(effects[0]))
    run = run_vector(document)
    state = run.final_state
    action = state.action_instances["1"]
    summary = {
        "tick": state.tick,
        "node": action.current_node_id,
        "lifecycle": action.lifecycle_state,
        "fault_record": action.fault_record,
        "transition_serial": action.transition_serial,
        "pending_events": list(state.pending_events),
        "input_buffer": [entry.__dict__ for entry in action.input_buffer],
    }
    case = vector["runtime_fault_case"]
    assert [trace["state_digest"] for trace in run.traces] == case[
        "tick_state_digests"
    ]
    assert state.state_hash() == case["final_state_digest"]
    assert summary == case["summary"]
    assert run.traces[1]["faults"][0]["fault"] == case["fault"]
    assert run.traces[1]["effects_emitted"] == []
