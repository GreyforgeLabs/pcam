import json
from pathlib import Path

from pcam_runtime.vectors import rollback_vector, run_vector

ROOT = Path(__file__).resolve().parents[3]


def _document():
    return json.loads((ROOT / "tests/vectors/typed-strike.json").read_text(encoding="utf-8"))


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
