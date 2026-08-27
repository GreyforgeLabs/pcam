import json
from pathlib import Path

from pcam_runtime.vectors import run_vector

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads(
        (ROOT / "tests/vectors/explicit-skip-runtime.json").read_text(encoding="utf-8")
    )


def test_python_explicit_skip_sets_only_declared_step_and_effect():
    vector = _vector()
    expected = vector["expected"]
    run = run_vector(vector)
    actions = [trace["state_changes"]["action_instances"][0] for trace in run.traces]

    assert [trace["state_digest"] for trace in run.traces] == expected["tick_state_digests"]
    assert [action["current_node_id"] for action in actions] == expected["node"]
    assert [action["node_step"] for action in actions] == expected["node_step"]
    assert [action["transition_serial"] for action in actions] == expected["transition_serial"]
    assert [trace["state_changes"]["resource_banks"]["1"]["skip_count"] for trace in run.traces] == expected["skip_count"]
    assert [len(trace["effects_emitted"]) for trace in run.traces] == expected["legacy_effect_count"]
