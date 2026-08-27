import json
from pathlib import Path

from pcam_runtime.vectors import run_vector

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads(
        (ROOT / "tests/vectors/simultaneous-trade-runtime.json").read_text(encoding="utf-8")
    )


def _document(vector, case, reverse=False):
    document = json.loads(json.dumps(vector))
    document["definitions"][0]["semantic_facts"][1]["fact"]["tags"] = case[
        "a_defense_tags"
    ]
    if reverse:
        document["ticks"][0]["contacts"].reverse()
    return document


def _summary(run):
    trace = run.traces[0]
    return {
        "resources": run.final_state.resource_banks,
        "candidate_order": trace["candidate_order"],
        "effects": [
            [effect["source_entity_id"], effect["target_entity_id"], effect["payload"]]
            for effect in trace["typed_effects_emitted"]
        ],
    }


def test_python_simultaneous_trade_and_armored_outgoing_are_permutation_invariant():
    vector = _vector()
    for case in vector["cases"]:
        forward = run_vector(_document(vector, case))
        reverse = run_vector(_document(vector, case, reverse=True))

        assert _summary(forward) == case["expected"], case["id"]
        assert _summary(reverse) == case["expected"], case["id"]
        assert forward.final_state.state_hash() == case["final_state_digest"]
        assert reverse.final_state.state_hash() == case["final_state_digest"]
