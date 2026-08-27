import json
from pathlib import Path

from pcam_runtime import RetainedRollbackHistory
from pcam_runtime.vectors import rollback_vector, run_vector

ROOT = Path(__file__).resolve().parents[3]


def _document():
    return json.loads((ROOT / "tests/vectors/typed-strike.json").read_text(encoding="utf-8"))


def _parent_child_document():
    return json.loads((ROOT / "tests/vectors/parent-child.json").read_text(encoding="utf-8"))


def _contended_starts_document():
    return json.loads((ROOT / "tests/vectors/contended-starts.json").read_text(encoding="utf-8"))


def _presentation_document():
    return json.loads((ROOT / "tests/vectors/presentation-rollback.json").read_text(encoding="utf-8"))


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


def test_python_contended_starts_match_shared_arbitration_state_digest():
    document = _contended_starts_document()
    expected = document["expected"]
    run = run_vector(document)

    assert run.executor.definition_set_hash == expected["definition_set_hash"]
    assert {
        identifier: definition.definition_hash
        for identifier, definition in run.executor.definitions_by_id.items()
    } == expected["definition_hashes"]
    assert [trace["state_digest"] for trace in run.traces] == expected["tick_state_digests"]
    assert run.final_state.state_hash() == expected["final_state_digest"]
    assert len(run.final_state.action_instances) == 1
    assert run.final_state.action_instances["1"].definition_hash == expected["definition_hashes"]["DODGE_A"]
    assert run.final_state.resource_banks["1"]["STAMINA"] == 3
    assert run.final_state.action_slots["1"]["FULL_BODY"] == {
        "capacity": 1,
        "instance_ids": [1],
        "usage": 1,
    }


def _advance_document(manager, state, run, document, tick_zero_inputs=None):
    for tick_index in range(len(document["ticks"])):
        inputs = run.input_history[tick_index]
        if tick_index == 0 and tick_zero_inputs is not None:
            inputs = tick_zero_inputs
        state, _, _ = manager.advance(state, inputs, run.host_history[tick_index])
    return state


def test_python_presentation_reconciliation_matches_shared_emit_suppress_and_invalidate():
    document = _presentation_document()
    run = run_vector(document)
    expected = document["expected"]
    expected_id = expected["presentation_effect_id"]
    initial = run.executor.restore(run.initial_snapshot)

    actual = RetainedRollbackHistory(run.executor, 4)
    state = _advance_document(actual, initial, run, document)
    assert state.state_hash() == expected["final_state_digest"]
    replayed = actual.correct_and_resimulate(0, run.input_history[0])
    assert replayed.presentation_suppressed == (expected_id,)
    assert replayed.presentation_emit == ()
    assert replayed.presentation_invalidated == ()

    removed = RetainedRollbackHistory(run.executor, 4)
    _advance_document(removed, initial, run, document)
    correction = removed.correct_and_resimulate(0, ())
    assert correction.presentation_invalidated == (expected_id,)
    assert correction.presentation_emit == ()
    assert correction.presentation_suppressed == ()

    predicted = RetainedRollbackHistory(run.executor, 4)
    _advance_document(predicted, initial, run, document, tick_zero_inputs=())
    correction = predicted.correct_and_resimulate(0, run.input_history[0])
    assert correction.presentation_emit == (expected_id,)
    assert correction.presentation_invalidated == ()
    assert correction.presentation_suppressed == ()
