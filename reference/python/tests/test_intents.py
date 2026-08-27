from itertools import permutations

from pcam_runtime import ArbitrationState, Claim, Intent, allocate_action_instance_ids, arbitrate


def _intent(owner: int, priority: int, amount: int, input_id: str) -> Intent:
    return Intent(
        intent_kind="ACTION_START",
        intent_priority=priority,
        owner_entity_id=owner,
        source_action_instance_id=0,
        transition_id="START",
        input_sequence=1,
        input_id=input_id,
        claims=(Claim("RESOURCE", "STAMINA", amount), Claim("ACTION_SLOT", "FULL_BODY")),
        operations=({"start_action": "DODGE"},),
    )


def test_resource_and_slot_arbitration_is_permutation_invariant():
    intents = (_intent(1, 10, 7, "a"), _intent(1, 5, 7, "b"))
    initial = ArbitrationState(
        resource_banks={1: {"STAMINA": 10}},
        capacities={("ACTION_SLOT", 1, "FULL_BODY"): 1},
    )
    outcomes = []
    for order in permutations(intents):
        state, decisions = arbitrate(order, initial)
        outcomes.append((state, tuple((item.intent.input_id, item.accepted) for item in decisions)))
    assert all(item == outcomes[0] for item in outcomes)
    assert outcomes[0][0].resource_banks[1]["STAMINA"] == 3
    assert outcomes[0][1] == (("a", True), ("b", False))


def test_claims_are_atomic_and_do_not_partially_reserve():
    intent = _intent(1, 10, 7, "a")
    initial = ArbitrationState(
        resource_banks={1: {"STAMINA": 10}},
        capacities={("ACTION_SLOT", 1, "FULL_BODY"): 0},
    )
    state, decisions = arbitrate((intent,), initial)
    assert not decisions[0].accepted
    assert state.resource_banks[1]["STAMINA"] == 10


def test_instance_identifiers_follow_accepted_canonical_order():
    intents = (_intent(2, 10, 1, "b"), _intent(1, 10, 1, "a"))
    initial = ArbitrationState(
        resource_banks={1: {"STAMINA": 2}, 2: {"STAMINA": 2}},
        capacities={
            ("ACTION_SLOT", 1, "FULL_BODY"): 1,
            ("ACTION_SLOT", 2, "FULL_BODY"): 1,
        },
    )
    _, decisions = arbitrate(intents, initial)
    allocated, next_id = allocate_action_instance_ids(decisions, 40)
    assert allocated[decisions[0].intent.identity] == 40
    assert allocated[decisions[1].intent.identity] == 41
    assert next_id == 42
