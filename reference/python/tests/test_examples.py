from pathlib import Path

from pcam_runtime import (
    Contact,
    HostSnapshot,
    InteractionCandidate,
    SemanticFact,
    TickExecutor,
    TickInput,
    action_from_document,
    canonical_dumps,
    canonical_hash,
    interaction_rules_from_document,
    load_document,
    resolve_candidate,
    validate_document,
)

ROOT = Path(__file__).resolve().parents[3]


def _execute_scenario(scenario):
    documents = [load_document(ROOT / path) for path in scenario["actions"]]
    interaction_document = load_document(ROOT / scenario["interaction_profile"])
    assert all(validate_document(document) == [] for document in documents)
    assert validate_document(interaction_document) == []

    definitions = tuple(action_from_document(document) for document in documents)
    rules = interaction_rules_from_document(interaction_document)
    registry = {
        effect_type: (str(value[0]), int(value[1]))
        for effect_type, value in scenario["effect_registry"].items()
    }
    executor = TickExecutor(definitions, interaction_rules=rules, effect_registry=registry)
    heavy = next(item for item in definitions if item.id == "greyforge.example.heavy_strike")
    state = executor.initial_state(
        resource_banks={
            "1": {"STAMINA": 100, "hp": 100, "stagger": 0},
            "2": {"STAMINA": 100, "hp": 100, "stagger": 0},
        },
        slot_capacities={"1": {"FULL_BODY": 1}, "2": {"FULL_BODY": 1}},
    )
    starts = (
        TickInput("start-a", 1, 0, "START", 0, action_definition_id=heavy.id),
        TickInput("start-b", 2, 0, "START", 0, action_definition_id=heavy.id),
    )
    contacts = (
        Contact("a-to-b", 1, 2, "heavy_strike_hit", source_entity_id=1, contact_id="a"),
        Contact("a-to-b-dup", 1, 2, "heavy_strike_hit", source_entity_id=1, contact_id="b"),
        Contact("b-to-a", 2, 1, "heavy_strike_hit", source_entity_id=2, contact_id="a"),
    )
    traces = []
    for tick in range(scenario["tick_count"]):
        host = HostSnapshot(contacts=contacts) if tick == scenario["contact_tick"] else HostSnapshot()
        state, trace = executor.tick(state, starts if tick == 0 else (), host)
        traces.append(trace)
    return documents, interaction_document, definitions, executor, state, traces


def test_canonical_examples_validate_execute_and_match_pinned_evidence():
    scenario = load_document(ROOT / "examples/heavy-strike.scenario.json")
    expected = scenario["expected"]
    documents, interaction, definitions, executor, state, traces = _execute_scenario(scenario)
    heavy = next(item for item in definitions if item.id == "greyforge.example.heavy_strike")

    assert canonical_hash(documents[0]) == expected["heavy_strike_document_hash"]
    assert heavy.definition_hash == expected["heavy_strike_runtime_hash"]
    assert canonical_hash(interaction) == expected["interaction_document_hash"]
    assert executor.definition_set_hash == expected["definition_set_hash"]
    assert canonical_hash(traces) == expected["trace_digest"]
    assert state.state_hash() == expected["final_state_digest"]
    assert state.resource_banks == expected["resource_banks"]
    assert all(action.lifecycle_state == "TERMINATED" for action in state.action_instances.values())

    change_ticks = [trace["tick"] for trace in traces if trace.get("node_changes")]
    assert change_ticks == expected["node_change_ticks"]
    contact_trace = traces[scenario["contact_tick"]]
    assert contact_trace["candidate_order"] == expected["candidate_order"]
    assert [item["accepted"] for item in contact_trace["decision_record_mutations"]] == [True, False, True]
    assert [item["value"] for item in contact_trace["effect_reduction"] if item["effect_type"] == "combat.stagger"] == [0, 0]

    rerun = _execute_scenario(scenario)
    assert canonical_dumps(rerun[-1]) == canonical_dumps(traces)
    assert rerun[-2].to_snapshot() == state.to_snapshot()


def test_canonical_interaction_example_parries_only_the_incoming_candidate():
    interaction = load_document(ROOT / "examples/combat.interaction.yaml")
    rules = interaction_rules_from_document(interaction)
    heavy = action_from_document(load_document(ROOT / "examples/heavy-strike.action.yaml"))
    offense = next(binding.fact for binding in heavy.semantic_facts if binding.fact.direction == "OFFENSE")
    candidate = InteractionCandidate(24, "parried", 1, 2, 1, offense.fact_id, "contact")
    decision = resolve_candidate(
        candidate,
        offense,
        {2: SemanticFact("parry", "DEFENSE", tags=("PARRY",))},
        rules,
    )
    assert decision.status == "REJECTED"
    assert "PARRIED" in decision.decision_tags
    assert decision.generated_effects == ()
    reaction = next(item for item in decision.active_effect_templates if item.effect_class == "REACTION")
    assert reaction.payload == {"attacker": 1}
