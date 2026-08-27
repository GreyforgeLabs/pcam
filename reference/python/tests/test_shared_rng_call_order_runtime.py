import copy
import json
from pathlib import Path

import pytest

from pcam_runtime import HostSnapshot, PCAMError, TickInput
from pcam_runtime.vectors import run_vector

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads(
        (ROOT / "tests/vectors/rng-call-order-runtime.json").read_text(
            encoding="utf-8"
        )
    )


def _inputs(tick):
    return tuple(
        TickInput(
            input_id=item["input_id"],
            source_entity_id=item["source_entity_id"],
            sequence=item["sequence"],
            command_id=item["command_id"],
            assigned_tick=item["assigned_tick"],
            action_definition_id=item.get("action_definition_id"),
        )
        for item in tick["inputs"]
    )


def test_python_shared_rng_call_order_is_permutation_and_restore_invariant():
    vector = _vector()
    expected = vector["expected"]
    forward = run_vector(vector)
    reversed_document = copy.deepcopy(vector)
    for tick in reversed_document["ticks"]:
        tick["inputs"].reverse()
    reversed_run = run_vector(reversed_document)

    assert {
        identifier: definition.definition_hash
        for identifier, definition in forward.executor.definitions_by_id.items()
    } == expected["definition_hashes"]
    assert forward.executor.definition_set_hash == expected["definition_set_hash"]
    assert [trace["state_digest"] for trace in forward.traces] == expected[
        "tick_state_digests"
    ]
    assert [trace["effect_reduction"] for trace in forward.traces] == expected[
        "rng_draws"
    ]
    assert forward.final_state.rng_streams["shared.simulation"] == expected[
        "final_stream"
    ]
    assert forward.final_state.state_hash() == expected["final_state_digest"]
    assert reversed_run.final_state.to_snapshot() == forward.final_state.to_snapshot()
    assert [trace["effect_reduction"] for trace in reversed_run.traces] == expected[
        "rng_draws"
    ]

    partial_document = copy.deepcopy(vector)
    partial_document["ticks"] = partial_document["ticks"][:2]
    partial = run_vector(partial_document)
    restored = partial.executor.restore(partial.executor.save(partial.final_state))
    continued, trace = partial.executor.tick(
        restored,
        _inputs(vector["ticks"][2]),
        HostSnapshot(),
    )
    assert trace["effect_reduction"] == expected["rng_draws"][2]
    assert continued.state_hash() == expected["final_state_digest"]


@pytest.mark.parametrize(
    ("mutation", "fault"),
    [
        ("missing-stream", "RNG_PROFILE_MISMATCH"),
        ("draw-count-overflow", "INTEGER_OVERFLOW"),
    ],
)
def test_python_shared_rng_faults_are_tick_atomic(mutation, fault):
    document = _vector()
    stream = document["initial_state"]["rng_streams"]["shared.simulation"]
    if mutation == "missing-stream":
        document["initial_state"]["rng_streams"] = {}
    else:
        stream["draw_count"] = 18446744073709551615
    first_tick = copy.deepcopy(document)
    first_tick["ticks"] = first_tick["ticks"][:1]
    partial = run_vector(first_tick)
    before = partial.final_state.to_snapshot()
    with pytest.raises(PCAMError) as raised:
        partial.executor.tick(
            partial.final_state,
            _inputs(document["ticks"][1]),
            HostSnapshot(),
        )
    assert raised.value.fault.value == fault
    assert partial.final_state.to_snapshot() == before


@pytest.mark.parametrize(
    "mutation",
    [
        "algorithm-mismatch",
        "undeclared-profile",
        "missing-field",
        "wrong-field-type",
        "extra-field",
    ],
)
def test_python_shared_rng_snapshot_contract_fails_before_execution(mutation):
    document = _vector()
    stream = document["initial_state"]["rng_streams"]["shared.simulation"]
    if mutation == "algorithm-mismatch":
        stream["algorithm_id"] = "pcam.unknown.v1"
    elif mutation == "undeclared-profile":
        document["runtime_profile"]["rng_profiles"] = ["pcam.unknown.v1"]
    elif mutation == "missing-field":
        stream.pop("stream_selector")
    elif mutation == "wrong-field-type":
        stream["draw_count"] = "0"
    else:
        stream["extra"] = 0
    with pytest.raises(PCAMError) as raised:
        run_vector(document)
    assert raised.value.fault.value == "RNG_PROFILE_MISMATCH"


def test_python_shared_rng_restore_revalidates_profile_binding():
    document = _vector()
    partial = copy.deepcopy(document)
    partial["ticks"] = partial["ticks"][:1]
    run = run_vector(partial)
    snapshot = run.executor.save(run.final_state)
    snapshot["rng_streams"]["shared.simulation"]["algorithm_id"] = "pcam.unknown.v1"
    with pytest.raises(PCAMError) as raised:
        run.executor.restore(snapshot)
    assert raised.value.fault.value == "RNG_PROFILE_MISMATCH"
