import json
from pathlib import Path

from pcam_runtime.vectors import run_vector

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads(
        (ROOT / "tests/vectors/transition-context-runtime.json").read_text(encoding="utf-8")
    )


def test_python_complete_state_transition_context_matches_shared_vectors():
    vector = _vector()
    for case in vector["cases"]:
        document = json.loads(json.dumps(vector))
        document["ticks"][1]["imports"]["allowed"] = case["allowed"]
        run = run_vector(document)
        state = run.final_state
        action = state.action_instances["1"]
        summary = {
            "node": action.current_node_id,
            "transition_serial": action.transition_serial,
            "input_buffer": [entry.__dict__ for entry in action.input_buffer],
            "host_imports": state.host_state["imports"],
        }
        assert [trace["state_digest"] for trace in run.traces] == case["tick_state_digests"]
        assert state.state_hash() == case["final_state_digest"], case["id"]
        assert summary == case["expected"], case["id"]
