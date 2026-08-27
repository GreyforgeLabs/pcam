import json
from pathlib import Path

from pcam_runtime import HostSnapshot, TickInput
from pcam_runtime.vectors import run_vector

ROOT = Path(__file__).resolve().parents[3]


def _documents():
    overlay = json.loads((ROOT / "tests/vectors/rng-freeze-runtime.json").read_text())
    document = json.loads((ROOT / overlay["base_vector"]).read_text())
    document["initial_state"]["freeze_tokens"] = [overlay["freeze_token"]]
    document["initial_state"]["next_freeze_token_id"] = 2
    return document, overlay["expected"]


def test_python_rng_consumption_freeze_is_targeted_expires_and_restores():
    document, expected = _documents()
    run = run_vector(document)
    assert run.executor.definition_set_hash == expected["definition_set_hash"]
    assert [trace["state_digest"] for trace in run.traces] == expected["tick_state_digests"]
    assert [trace["effect_reduction"] for trace in run.traces] == expected["rng_draws"]
    assert run.final_state.rng_streams["shared.simulation"] == expected["final_stream"]
    assert run.final_state.freeze_tokens == ()

    partial = dict(document)
    partial["ticks"] = document["ticks"][:2]
    first = run_vector(partial)
    restored = first.executor.restore(first.executor.save(first.final_state))
    inputs = tuple(
        TickInput(item["input_id"], item["source_entity_id"], item["sequence"], item["command_id"], item["assigned_tick"])
        for item in document["ticks"][2]["inputs"]
    )
    continued, trace = first.executor.tick(restored, inputs, HostSnapshot())
    assert trace["effect_reduction"] == expected["rng_draws"][2]
    assert continued.state_hash() == expected["final_state_digest"]
