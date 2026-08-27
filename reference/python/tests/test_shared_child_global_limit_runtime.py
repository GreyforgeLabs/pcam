import copy
import json
from pathlib import Path

import pytest

from pcam_runtime import HostSnapshot, PCAMError, TickInput
from pcam_runtime.vectors import run_vector

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads((ROOT / "tests/vectors/child-global-limit-runtime.json").read_text())


def _document(vector, case):
    document = copy.deepcopy(vector)
    document["runtime_profile"]["limits"]["max_children_per_action"] = case[
        "max_children_per_action"
    ]
    document["ticks"] = document["ticks"][: 2 if "fault" in case else 3]
    return document


def test_python_child_global_limit_matches_shared_success_and_atomic_fault():
    vector = _vector()
    for case in vector["cases"]:
        run = run_vector(_document(vector, case))
        assert run.executor.definition_set_hash == case["definition_set_hash"]
        if "fault" not in case:
            state = run.final_state
            assert [trace["state_digest"] for trace in run.traces] == case[
                "tick_state_digests"
            ]
            assert {
                "next_action_instance_id": state.next_action_instance_id,
                "parents": {key: item.parent_instance_id for key, item in state.action_instances.items()},
                "parent_slots": {key: item.parent_slot_id for key, item in state.action_instances.items()},
                "children": {key: list(item.child_instance_ids) for key, item in state.action_instances.items()},
                "lifecycle": {key: item.lifecycle_state for key, item in state.action_instances.items()},
            } == case["expected"]
            continue

        before = run.final_state.to_snapshot()
        raw = vector["ticks"][2]["inputs"][0]
        with pytest.raises(PCAMError) as raised:
            run.executor.tick(
                run.final_state,
                (TickInput(raw["input_id"], raw["source_entity_id"], raw["sequence"], raw["command_id"], raw["assigned_tick"]),),
                HostSnapshot(),
            )
        assert raised.value.fault.value == case["fault"]
        assert run.final_state.state_hash() == case["pre_fault_digest"]
        assert run.final_state.to_snapshot() == before
