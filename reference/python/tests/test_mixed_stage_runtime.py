import json
from pathlib import Path

from pcam_runtime import RetainedRollbackHistory
from pcam_runtime.vectors import run_vector

ROOT = Path(__file__).resolve().parents[3]

STAGES = [
    "tick_start_snapshot",
    "input_ingestion",
    "pre_advance_intent_evaluation",
    "pre_advance_arbitration",
    "action_progression",
    "post_advance_intent_evaluation_and_arbitration",
    "semantic_snapshot",
    "contact_and_candidate_generation",
    "interaction_resolution",
    "effect_reduction_and_commit",
    "maintenance",
    "snapshot_and_digest",
]


def _document():
    return json.loads(
        (ROOT / "tests/vectors/mixed-stage-runtime.json").read_text(encoding="utf-8")
    )


def test_python_mixed_stage_runtime_matches_exact_pipeline_evidence():
    document = _document()
    expected = document["expected"]
    run = run_vector(document)

    assert run.executor.definition_set_hash == expected["definition_set_hash"]
    assert {
        identifier: definition.definition_hash
        for identifier, definition in run.executor.definitions_by_id.items()
    } == expected["definition_hashes"]
    assert [trace["state_digest"] for trace in run.traces] == expected[
        "tick_state_digests"
    ]
    assert run.final_state.state_hash() == expected["final_state_digest"]
    assert all(
        [stage["name"] for stage in trace["stages"]] == STAGES for trace in run.traces
    )

    interaction = run.traces[1]
    assert interaction["candidate_order"] == ["child-strike"]
    assert [
        [effect["effect_class"], effect["payload"]]
        for effect in interaction["typed_effects_emitted"]
    ] == [["DAMAGE", 7]]
    assert interaction["provisional_receipts"] == [
        {"candidate_id": "child-strike", "receipt_written": True}
    ]
    assert interaction["effect_reduction"][0]["value"] == 7
    assert run.traces[3]["events_delivered"] == ["child-result:3:1"]

    state = run.final_state
    assert state.resource_banks["2"]["hp"] == 43
    assert len(state.interaction_ledgers) == 1
    assert state.action_instances["1"].lifecycle_state == "TERMINATED"
    assert state.action_instances["2"].lifecycle_state == "RUNNING"
    assert state.action_instances["3"].lifecycle_state == "TERMINATED"


def test_python_mixed_stage_snapshot_restores_and_continues_exactly():
    document = _document()
    expected = document["expected"]
    run = run_vector(document)
    uninterrupted = run.executor.restore(run.initial_snapshot)
    for tick_index in range(2):
        uninterrupted, _ = run.executor.tick(
            uninterrupted,
            run.input_history[tick_index],
            run.host_history[tick_index],
        )

    assert uninterrupted.state_hash() == expected["mid_state_digest"]
    assert uninterrupted.resource_banks["2"]["hp"] == 43
    assert len(uninterrupted.interaction_ledgers) == 1
    assert uninterrupted.next_action_instance_id == 4
    assert uninterrupted.next_freeze_token_id == 2
    assert uninterrupted.action_instances["1"].child_instance_ids == (3,)
    assert uninterrupted.action_instances["3"].parent_instance_id == 1
    assert len(uninterrupted.freeze_tokens) == 1

    restored = run.executor.restore(run.executor.save(uninterrupted))
    assert restored.to_snapshot() == uninterrupted.to_snapshot()
    for tick_index in range(2, len(document["ticks"])):
        uninterrupted, left = run.executor.tick(
            uninterrupted,
            run.input_history[tick_index],
            run.host_history[tick_index],
        )
        restored, right = run.executor.tick(
            restored,
            run.input_history[tick_index],
            run.host_history[tick_index],
        )
        assert left["state_digest"] == right["state_digest"]
        assert left["typed_effects_emitted"] == right["typed_effects_emitted"]

    assert restored.to_snapshot() == uninterrupted.to_snapshot()
    assert restored.state_hash() == expected["final_state_digest"]


def test_python_mixed_stage_retained_correction_matches_direct_execution():
    document = _document()
    expected = document["expected"]
    run = run_vector(document)
    initial = run.executor.restore(run.initial_snapshot)

    history = RetainedRollbackHistory(run.executor, 8)
    predicted = initial
    for tick_index in range(len(document["ticks"])):
        predicted, _, _ = history.advance(
            predicted,
            run.input_history[tick_index],
            run.host_history[tick_index],
        )
    assert predicted.state_hash() == expected["final_state_digest"]

    corrected = history.correct_and_resimulate(expected["corrected_tick"], ())
    assert [trace["state_digest"] for trace in corrected.traces] == expected[
        "corrected_tick_state_digests"
    ]
    assert corrected.state.state_hash() == expected["corrected_final_state_digest"]

    direct = initial
    for tick_index in range(len(document["ticks"])):
        inputs = () if tick_index == expected["corrected_tick"] else run.input_history[tick_index]
        direct, _ = run.executor.tick(direct, inputs, run.host_history[tick_index])
    assert corrected.state.to_snapshot() == direct.to_snapshot()
    assert corrected.state.resource_banks["2"]["hp"] == 50
    assert corrected.state.interaction_ledgers == {}
    assert set(corrected.state.action_instances) == {"1", "2"}


def test_python_mixed_stage_raw_start_order_is_invariant():
    document = _document()
    reversed_document = json.loads(json.dumps(document))
    reversed_document["ticks"][0]["inputs"].reverse()
    direct = run_vector(document)
    reversed_run = run_vector(reversed_document)

    assert reversed_run.final_state.to_snapshot() == direct.final_state.to_snapshot()
    assert [trace["state_digest"] for trace in reversed_run.traces] == document[
        "expected"
    ]["tick_state_digests"]
