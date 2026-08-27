import json
from pathlib import Path

from pcam_runtime.vectors import run_vector

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads(
        (ROOT / "tests/vectors/initial-entry-effects-runtime.json").read_text(
            encoding="utf-8"
        )
    )


def test_python_initial_entry_effects_match_shared_vector():
    vector = _vector()
    expected = vector["expected"]
    run = run_vector(vector)
    state = run.final_state
    summary = {
        "tick": state.tick,
        "stamina": state.resource_banks["1"]["STAMINA"],
        "next_action_instance_id": state.next_action_instance_id,
        "actions": {
            key: {
                "definition_hash": action.definition_hash,
                "lifecycle": action.lifecycle_state,
                "marker": action.registers["marker"],
                "emission_serial": action.emission_serial,
                "transition_serial": action.transition_serial,
                "parent_instance_id": action.parent_instance_id,
                "parent_slot_id": action.parent_slot_id,
                "child_instance_ids": list(action.child_instance_ids),
            }
            for key, action in state.action_instances.items()
        },
    }
    assert {
        identifier: definition.definition_hash
        for identifier, definition in run.executor.definitions_by_id.items()
    } == expected["definition_hashes"]
    assert state.definition_set_hash == expected["definition_set_hash"]
    assert [trace["state_digest"] for trace in run.traces] == expected[
        "tick_state_digests"
    ]
    assert state.state_hash() == expected["final_state_digest"]
    assert summary == expected["summary"]
    assert [
        {
            "emitted": trace["typed_effects_emitted"],
            "reduced": trace["effect_reduction"],
        }
        for trace in run.traces
    ] == expected["traces"]
