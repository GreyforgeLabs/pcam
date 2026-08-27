from pcam_runtime import (
    ActionDefinition,
    Contact,
    Effect,
    HostSnapshot,
    NodeDefinition,
    PredicateDefinition,
    RollbackManager,
    TickExecutor,
    TickInput,
    TransitionDefinition,
)


def _definition() -> ActionDefinition:
    return ActionDefinition(
        id="STRIKE",
        rate_scale=5,
        units_per_tick=2,
        nodes=(
            NodeDefinition(id="WINDUP"),
            NodeDefinition(id="ACTIVE"),
            NodeDefinition(id="RECOVER"),
        ),
        predicates=(PredicateDefinition(id="HIT_ACTIVE", node_ids=("ACTIVE",)),),
        transitions=(
            TransitionDefinition(
                id="windup_to_active",
                source_node="WINDUP",
                evaluation_point="AFTER_QUANTUM",
                priority=10,
                target_node="ACTIVE",
            ),
            TransitionDefinition(
                id="active_to_recover",
                source_node="ACTIVE",
                evaluation_point="AFTER_QUANTUM",
                priority=10,
                target_node="RECOVER",
            ),
        ),
    )


def _start_input(tick: int = 0) -> TickInput:
    return TickInput(
        input_id=f"i-{tick}",
        source_entity_id=1,
        sequence=tick,
        command_id="START_STRIKE",
        assigned_tick=tick,
        action_definition_id="STRIKE",
    )


def test_tick_executor_runs_ordered_vertical_slice_with_rational_progression_and_trace():
    executor = TickExecutor((_definition(),))
    state = executor.initial_state(resource_banks={"2": {"hp": 10}})

    state, trace0 = executor.tick(state, (_start_input(),))
    assert [stage["index"] for stage in trace0["stages"]] == list(range(1, 13))
    assert state.tick == 1
    action = state.action_instances["1"]
    assert action.quantum_accumulator == 2
    assert action.current_node_id == "WINDUP"

    state, trace1 = executor.tick(state)
    assert trace1["progression_quanta"]["1"] == 0
    assert state.action_instances["1"].quantum_accumulator == 4

    state, trace2 = executor.tick(state)
    action = state.action_instances["1"]
    assert trace2["progression_quanta"]["1"] == 1
    assert action.current_node_id == "ACTIVE"
    assert action.transition_serial == 1
    assert action.predicate_entry_serials["HIT_ACTIVE"] == 1
    assert "state_digest" in trace2


def test_once_per_action_ledger_effect_commit_snapshot_restore_and_digest_equivalence():
    executor = TickExecutor((_definition(),))
    state = executor.initial_state(resource_banks={"2": {"hp": 10}})
    state, _ = executor.tick(state, (_start_input(),))
    state, _ = executor.tick(state)
    state, _ = executor.tick(state)
    assert state.action_instances["1"].current_node_id == "ACTIVE"

    contact = Contact(
        candidate_id="c1",
        source_instance_id=1,
        target_entity_id=2,
        fact_id="HIT_ACTIVE",
        effect=Effect(id="damage", target_entity_id=2, resource="hp", amount=-3),
    )
    duplicate = Contact(
        candidate_id="c2",
        source_instance_id=1,
        target_entity_id=2,
        fact_id="HIT_ACTIVE",
        effect=Effect(id="damage-duplicate", target_entity_id=2, resource="hp", amount=-3),
    )
    state, trace = executor.tick(state, host=HostSnapshot(contacts=(duplicate, contact)))
    assert state.resource_banks["2"]["hp"] == 7
    assert len(state.interaction_ledgers) == 1
    assert [receipt["accepted"] for receipt in trace["decision_record_mutations"]] == [True, False]

    snapshot = executor.save(state)
    restored = executor.restore(snapshot)
    assert restored.to_snapshot() == state.to_snapshot()
    assert restored.state_hash() == state.state_hash()


def test_rollback_correction_matches_direct_correct_execution():
    executor = TickExecutor((_definition(),))
    baseline = executor.initial_state(resource_banks={"2": {"hp": 10}})
    baseline_snapshot = executor.save(baseline)

    direct = baseline
    direct, _ = executor.tick(direct, (_start_input(),))
    direct, _ = executor.tick(direct)
    direct, _ = executor.tick(direct)

    manager = RollbackManager(executor)
    corrected, traces = manager.correct_and_resimulate(
        baseline_snapshot=baseline_snapshot,
        input_history={},
        host_history={},
        corrected_tick=0,
        corrected_inputs=(_start_input(),),
        until_tick=3,
    )
    assert traces[-1]["state_digest"] == direct.state_hash()
    assert corrected.to_snapshot() == direct.to_snapshot()
