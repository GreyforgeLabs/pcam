import json
from pathlib import Path

from pcam_runtime.vectors import run_vector

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads((ROOT / "tests/vectors/ledger-runtime.json").read_text(encoding="utf-8"))


def test_python_complete_runtime_matches_shared_ledger_policy_outcomes():
    vector = _vector()
    for case in vector["cases"]:
        document = json.loads(json.dumps(vector))
        document["definitions"][0]["semantic_facts"][0]["hit_policy"] = case["policy"]
        if "extra_transition" in case:
            document["definitions"][0]["transitions"].append(case["extra_transition"])
        document["ticks"] = case["ticks"]
        run = run_vector(document)
        state = run.final_state
        summary = {
            "hp": state.resource_banks["2"]["hp"],
            "ledger_count": len(state.interaction_ledgers),
            "ledger_origin_ticks": sorted(
                receipt["origin_tick"] for receipt in state.interaction_ledgers.values()
            ),
            "effects_by_tick": [
                [effect["effect_id"] for effect in trace["typed_effects_emitted"]]
                for trace in run.traces
            ],
            "accepted_by_tick": [
                [receipt["accepted"] for receipt in trace["decision_record_mutations"]]
                for trace in run.traces
            ],
            "receipt_written_by_tick": [
                [receipt.get("receipt_written") for receipt in trace["decision_record_mutations"]]
                for trace in run.traces
            ],
            "reasons_by_tick": [
                [receipt.get("reason") for receipt in trace["decision_record_mutations"]]
                for trace in run.traces
            ],
            "predicate_entry_serials": state.action_instances["1"].predicate_entry_serials,
            "predicate_exit_serials": state.action_instances["1"].predicate_exit_serials,
        }
        if "cycle" in case["expected"]:
            summary["cycle"] = state.action_instances["1"].cycle
        assert state.action_instances["1"].definition_hash == case["definition_hash"]
        assert run.executor.definition_set_hash == case["definition_set_hash"]
        assert [trace["state_digest"] for trace in run.traces] == case["tick_state_digests"]
        assert state.state_hash() == case["final_state_digest"]
        assert summary == case["expected"], case["id"]
