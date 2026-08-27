import json
from pathlib import Path

from pcam_runtime import (
    ActionDefinition,
    Claim,
    Contact,
    EffectTemplate,
    FactBinding,
    HitPolicy,
    HostSnapshot,
    InteractionRule,
    NodeDefinition,
    PredicateDefinition,
    RuleOperation,
    RuntimeProfile,
    SemanticFact,
    TickExecutor,
    TickInput,
    TransitionDefinition,
)

ROOT = Path(__file__).resolve().parents[3]


def _trace_definition():
    return ActionDefinition(
        "TRACE",
        1,
        0,
        (NodeDefinition("RUN"), NodeDefinition("DONE")),
        transitions=(
            TransitionDefinition(
                "expensive",
                "RUN",
                "PRE_ADVANCE",
                20,
                target_node="DONE",
                input_command="GO",
                consume_policy="ON_ATTEMPT",
                claims=(Claim("RESOURCE", "stamina", 10),),
            ),
            TransitionDefinition(
                "fallback",
                "RUN",
                "PRE_ADVANCE",
                10,
                target_node="DONE",
                input_command="GO",
            ),
        ),
        default_buffer_lifetime=2,
    )


def test_trace_records_all_eligible_transitions_and_rejected_claim_details():
    executor = TickExecutor((_trace_definition(),))
    state = executor.initial_state(resource_banks={"1": {"stamina": 5}})
    state, _ = executor.tick(
        state,
        (TickInput("start", 1, 0, "START", 0, action_definition_id="TRACE"),),
    )
    go = TickInput("go", 1, 1, "GO", 1)
    state, trace = executor.tick(state, (go,))

    assert [item["transition_id"] for item in trace["eligible_transitions"]] == [
        "expensive",
        "fallback",
    ]
    assert trace["selected_transitions"] == []
    assert trace["rejected_intents"][0]["transition_id"] == "expensive"
    assert trace["claim_failures"][0]["reason"] == "RESOURCE_UNAVAILABLE:1:stamina"
    assert trace["resource_reservations"] == []
    assert state.action_instances["1"].input_buffer == ()


def test_trace_records_accepted_resource_reservation_and_selection():
    executor = TickExecutor((_trace_definition(),))
    state = executor.initial_state(resource_banks={"1": {"stamina": 20}})
    state, _ = executor.tick(
        state,
        (TickInput("start", 1, 0, "START", 0, action_definition_id="TRACE"),),
    )
    state, trace = executor.tick(state, (TickInput("go", 1, 1, "GO", 1),))

    assert trace["selected_transitions"][0]["transition_id"] == "expensive"
    assert trace["resource_reservations"] == [
        {
            "amount": 10,
            "intent_id": "1:1:expensive:1:go",
            "owner_entity_id": 1,
            "resource": "stamina",
        }
    ]
    assert state.resource_banks["1"]["stamina"] == 10


def test_trace_records_interaction_rules_and_provisional_receipts():
    fact = FactBinding(
        SemanticFact(
            "strike",
            "OFFENSE",
            effect_templates=(EffectTemplate("combat.damage", "DAMAGE", 3, "SUM"),),
        ),
        "ACTIVE",
        HitPolicy("ONCE_PER_ACTION_INSTANCE", "ON_IMPACT"),
    )
    definition = ActionDefinition(
        "STRIKE",
        1,
        0,
        (NodeDefinition("RUN"),),
        predicates=(PredicateDefinition("ACTIVE", node_ids=("RUN",)),),
        semantic_facts=(fact,),
    )
    rule = InteractionRule(
        "materialize",
        "MATERIALIZATION",
        1,
        {"literal": True},
        (RuleOperation("MATERIALIZE"),),
    )
    executor = TickExecutor((definition,), interaction_rules=(rule,))
    state = executor.initial_state(resource_banks={"2": {"hp": 10}})
    state, _ = executor.tick(
        state,
        (TickInput("start", 1, 0, "START", 0, action_definition_id="STRIKE"),),
    )
    contact = Contact("hit", 1, 2, "strike", source_entity_id=1, contact_id="hit")
    _, trace = executor.tick(state, host=HostSnapshot(contacts=(contact,)))

    assert trace["contact_candidates"][0]["candidate_id"] == "hit"
    assert trace["interaction_rules_fired"] == [
        {"candidate_id": "hit", "order": 1, "rule_id": "materialize", "stage": "MATERIALIZATION"}
    ]
    assert trace["provisional_receipts"] == [{"candidate_id": "hit", "receipt_written": True}]


def test_fault_trace_is_complete_and_preserves_pre_tick_state():
    definition = ActionDefinition("TOO_FAST", 1, 2, (NodeDefinition("RUN"),))
    executor = TickExecutor((definition,), RuntimeProfile(max_quanta_per_action_per_tick=1))
    initial = executor.initial_state()
    result, trace, error = executor.tick_with_fault_trace(
        initial,
        (TickInput("start", 1, 0, "START", 0, action_definition_id="TOO_FAST"),),
    )

    assert error is not None and error.fault.value == "QUANTUM_LIMIT_EXCEEDED"
    assert result.to_snapshot() == initial.to_snapshot()
    assert trace["faults"][0]["fault"] == "QUANTUM_LIMIT_EXCEEDED"
    assert trace["state_digest"] == initial.state_hash()


def test_machine_trace_contract_maps_every_required_field_to_runtime_output():
    contract = json.loads((ROOT / "release/trace-contract.json").read_text())
    definition = ActionDefinition("EMPTY_TRACE", 1, 0, (NodeDefinition("RUN"),))
    executor = TickExecutor((definition,))
    state = executor.initial_state()
    _, trace = executor.tick(state)
    assert len(contract["fields"]) == 22
    assert set(contract["fields"].values()).issubset(trace)
    assert all((ROOT / path).is_file() for path in contract["evidence"])
