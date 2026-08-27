import json
from itertools import permutations
from pathlib import Path

from pcam_runtime import ArbitrationState, Claim, Intent, allocate_action_instance_ids, arbitrate

ROOT = Path(__file__).resolve().parents[3]


def _vectors():
    return json.loads((ROOT / "tests/vectors/arbitration.json").read_text(encoding="utf-8"))


def _capacity_map(values):
    return {(item["kind"], item["owner_id"], item["key"]): item["value"] for item in values}


def _state(value):
    return ArbitrationState(
        resource_banks={int(owner): dict(bank) for owner, bank in value["resource_banks"].items()},
        capacities=_capacity_map(value["capacities"]),
        usages=_capacity_map(value["usages"]),
        exclusive_keys=frozenset(value["exclusive_keys"]),
    )


def _intents(values):
    return tuple(
        Intent(
            **{
                **value,
                "claims": tuple(Claim(**claim) for claim in value.get("claims", ())),
                "releases": tuple(Claim(**claim) for claim in value.get("releases", ())),
                "operations": tuple(value.get("operations", ())),
            }
        )
        for value in values
    )


def _decision_projection(decisions):
    return [
        {"input_id": item.intent.input_id, "accepted": item.accepted, "reason": item.reason}
        for item in decisions
    ]


def test_python_arbitration_matches_shared_atomic_claim_and_allocation_vectors():
    for case in _vectors()["cases"]:
        initial = _state(case["state"])
        intents = _intents(case["intents"])
        state, decisions = arbitrate(intents, initial)
        assert _decision_projection(decisions) == case["decisions"], case["id"]
        assert state.resource_banks == {
            int(owner): dict(bank) for owner, bank in case["expected_state"]["resource_banks"].items()
        }
        assert state.usages == _capacity_map(case["expected_state"]["usages"])
        assert state.exclusive_keys == frozenset(case["expected_state"]["exclusive_keys"])
        allocated, next_id = allocate_action_instance_ids(decisions, case["next_action_instance_id"])
        assert allocated == case["allocated"]
        assert next_id == case["next_id"]
        for order in permutations(intents):
            permuted_state, permuted_decisions = arbitrate(order, initial)
            assert permuted_state == state
            assert _decision_projection(permuted_decisions) == _decision_projection(decisions)
