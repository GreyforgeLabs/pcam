import json
from pathlib import Path

from pcam_runtime.vectors import rollback_vector, run_vector

ROOT = Path(__file__).resolve().parents[3]


def _document():
    return json.loads((ROOT / "tests/vectors/typed-strike.json").read_text(encoding="utf-8"))


def _parent_child_document():
    return json.loads((ROOT / "tests/vectors/parent-child.json").read_text(encoding="utf-8"))


def test_python_typed_strike_matches_shared_full_state_identity_and_tick_digests():
    document = _document()
    expected = document["expected"]
    run = run_vector(document)

    definition = next(iter(run.executor.definitions_by_id.values()))
    assert definition.definition_hash == expected["definition_hash"]
    assert run.executor.definition_set_hash == expected["definition_set_hash"]
    assert [trace["state_digest"] for trace in run.traces] == expected["tick_state_digests"]
    assert run.final_state.state_hash() == expected["final_state_digest"]
    assert run.traces[0]["candidate_order"] == ["c1", "c2"]
    assert run.traces[0]["typed_effects_emitted"][0]["effect_id"] == "0:1:c1:materialize:0:0"
    assert run.traces[0]["decision_record_mutations"][1]["reason"] == "ONCE_PER_ACTION_INSTANCE"


def test_python_typed_strike_shared_rollback_matches_direct_execution():
    direct, corrected, traces = rollback_vector(_document())

    assert corrected.to_snapshot() == direct.to_snapshot()
    assert traces[-1]["state_digest"] == direct.state_hash()


def test_python_parent_child_matches_shared_result_event_lifecycle_digests():
    document = _parent_child_document()
    expected = document["expected"]
    run = run_vector(document)

    assert run.executor.definition_set_hash == expected["definition_set_hash"]
    assert {
        identifier: definition.definition_hash
        for identifier, definition in run.executor.definitions_by_id.items()
    } == expected["definition_hashes"]
    assert [trace["state_digest"] for trace in run.traces] == expected["tick_state_digests"]
    assert run.final_state.state_hash() == expected["final_state_digest"]
    parent = run.final_state.action_instances["1"]
    child = run.final_state.action_instances["2"]
    assert (parent.current_node_id, parent.lifecycle_state, parent.transition_serial) == (
        "DONE",
        "TERMINATED",
        2,
    )
    assert child.extension_state["pcam.child_result_emitted"] is True
    assert run.final_state.pending_events == ()
    assert run.final_state.freeze_tokens == ()
