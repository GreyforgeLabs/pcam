import json
from pathlib import Path

from pcam_runtime import HostSnapshot, TickInput
from pcam_runtime.vectors import run_vector

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads((ROOT / "tests/vectors/rng-runtime.json").read_text(encoding="utf-8"))


def test_python_rng_effect_matches_shared_complete_state_and_restore_continuation():
    vector = _vector()
    run = run_vector(vector)
    expected = vector["expected"]

    assert [trace["state_digest"] for trace in run.traces] == expected["tick_state_digests"]
    assert [trace["effect_reduction"] for trace in run.traces] == expected["rng_draws"]
    assert run.final_state.rng_streams["main"] == expected["final_stream"]

    restored = run.executor.restore(run.executor.save(run.final_state))
    raw = vector["continuation_tick"]["inputs"][0]
    draw = TickInput(
        raw["input_id"],
        raw["source_entity_id"],
        raw["sequence"],
        raw["command_id"],
        raw["assigned_tick"],
    )
    continued, trace = run.executor.tick(restored, (draw,), HostSnapshot())

    assert trace["effect_reduction"] == [expected["continuation_draw"]]
    assert continued.state_hash() == expected["continuation_digest"]
