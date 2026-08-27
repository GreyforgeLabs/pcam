import copy
import json
from pathlib import Path

import pytest

from pcam_runtime import HostSnapshot, PCAMError, TickInput
from pcam_runtime.vectors import rollback_vector, run_vector

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads(
        (ROOT / "tests/vectors/custom-effect-runtime.json").read_text(
            encoding="utf-8"
        )
    )


def test_python_custom_effect_commits_hashes_and_restores_exactly():
    vector = _vector()
    expected = vector["expected"]
    run = run_vector(vector)
    assert {
        identifier: definition.definition_hash
        for identifier, definition in run.executor.definitions_by_id.items()
    } == expected["definition_hashes"]
    assert run.executor.definition_set_hash == expected["definition_set_hash"]
    assert [trace["state_digest"] for trace in run.traces] == expected[
        "tick_state_digests"
    ]
    assert run.final_state.resource_banks["1"]["score"] == expected["score"]
    assert run.final_state.state_hash() == expected["final_state_digest"]
    assert [
        {
            "emitted": trace["typed_effects_emitted"],
            "reduced": trace["effect_reduction"],
        }
        for trace in run.traces
    ] == expected["traces"]

    partial_document = copy.deepcopy(vector)
    partial_document["ticks"] = partial_document["ticks"][:1]
    partial = run_vector(partial_document)
    restored = partial.executor.restore(partial.executor.save(partial.final_state))
    continued, trace = partial.executor.tick(
        restored,
        (
            TickInput(
                input_id="start-2",
                source_entity_id=1,
                sequence=1,
                command_id="START",
                assigned_tick=1,
                action_definition_id="CUSTOM_SOURCE",
            ),
        ),
        HostSnapshot(),
    )
    assert continued.state_hash() == expected["final_state_digest"]
    assert trace["effect_reduction"] == expected["traces"][1]["reduced"]

    direct, corrected, traces = rollback_vector(vector)
    assert corrected.to_snapshot() == direct.to_snapshot()
    assert traces[-1]["state_digest"] == expected["final_state_digest"]


def test_python_custom_effect_registry_tampering_and_omission_fail_closed():
    vector = _vector()
    for field, value in (
        ("implementation_hash", "0" * 64),
        ("ordering_id", "pcam.order.unverified"),
        ("determinism_vectors", []),
        ("payload_schema", {"type": "string"}),
    ):
        document = copy.deepcopy(vector)
        document["custom_effect_registry"][0][field] = value
        with pytest.raises(PCAMError):
            run_vector(document)

    undeclared = copy.deepcopy(vector)
    undeclared["custom_effect_registry"] = []
    with pytest.raises(PCAMError) as raised:
        run_vector(undeclared)
    assert raised.value.fault.value == "UNKNOWN_EFFECT"
