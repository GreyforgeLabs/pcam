import json
from pathlib import Path

from pcam_runtime.vectors import run_vector

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads(
        (ROOT / "tests/vectors/once-freeze-runtime.json").read_text(encoding="utf-8")
    )


def test_python_once_per_action_does_not_rehit_during_or_after_freeze():
    vector = _vector()
    expected = vector["expected"]
    run = run_vector(vector)

    assert [trace["state_digest"] for trace in run.traces] == expected["tick_state_digests"]
    assert [trace["state_changes"]["resource_banks"]["2"]["hp"] for trace in run.traces] == expected["target_hp"]
    assert [len(trace["state_changes"]["interaction_ledgers"]) for trace in run.traces] == expected["ledger_count"]
    assert [len(trace["typed_effects_emitted"]) for trace in run.traces] == expected["effect_count"]
    assert [len(trace["decision_record_mutations"]) for trace in run.traces] == expected["receipt_count"]
    assert [len(trace["state_changes"]["freeze_tokens"]) for trace in run.traces] == expected["freeze_count"]
