from dataclasses import replace

from pcam_runtime import (
    ActionDefinition,
    Contact,
    Claim,
    Effect,
    EffectTemplate,
    FactBinding,
    FreezeToken,
    HostSnapshot,
    HitPolicy,
    InteractionRule,
    NodeDefinition,
    PredicateDefinition,
    RollbackManager,
    RuntimeProfile,
    RuleOperation,
    SemanticFact,
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
    assert snapshot["pcam_version"] == "3.0"
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


def test_buffered_pre_advance_input_is_consumed_on_transition_accept():
    definition = ActionDefinition(
        id="BUFFERED",
        rate_scale=1,
        units_per_tick=0,
        nodes=(NodeDefinition(id="WAIT"), NodeDefinition(id="DONE")),
        transitions=(
            TransitionDefinition(
                id="accept_dodge",
                source_node="WAIT",
                evaluation_point="PRE_ADVANCE",
                priority=10,
                input_command="DODGE",
                target_node="DONE",
            ),
        ),
        default_buffer_lifetime=2,
    )
    executor = TickExecutor((definition,))
    state = executor.initial_state()
    start = TickInput("start", 1, 0, "START", 0, action_definition_id="BUFFERED")
    state, _ = executor.tick(state, (start,))
    dodge = TickInput("dodge", 1, 1, "DODGE", 1)
    state, _ = executor.tick(state, (dodge,))
    action = state.action_instances["1"]
    assert action.current_node_id == "DONE"
    assert action.input_buffer == ()


def test_progression_freeze_hold_and_accrue_are_authoritative():
    definition = ActionDefinition(
        id="FREEZE",
        rate_scale=1,
        units_per_tick=1,
        nodes=(NodeDefinition(id="RUN"),),
    )
    executor = TickExecutor((definition,))
    state = executor.initial_state()
    start = TickInput("start", 1, 0, "START", 0, action_definition_id="FREEZE")
    state, _ = executor.tick(state, (start,))
    assert state.action_instances["1"].local_step == 1

    hold = FreezeToken.created(1, 1, 1, creation_tick=0, duration=1, domains=("PROGRESSION",))
    state = replace(state, freeze_tokens=(hold,))
    state, _ = executor.tick(state)
    assert state.action_instances["1"].local_step == 1
    assert state.freeze_tokens == ()

    accrue = FreezeToken.created(
        2,
        1,
        1,
        creation_tick=1,
        duration=1,
        domains=("PROGRESSION",),
        accrual_policy="ACCRUE",
    )
    state = replace(state, freeze_tokens=(accrue,))
    state, _ = executor.tick(state)
    assert state.action_instances["1"].local_step == 1
    assert state.action_instances["1"].deferred_quanta == 1
    state, _ = executor.tick(state)
    assert state.action_instances["1"].local_step == 3
    assert state.action_instances["1"].deferred_quanta == 0


def _typed_definition() -> ActionDefinition:
    return ActionDefinition(
        id="TYPED_STRIKE",
        rate_scale=1,
        units_per_tick=0,
        nodes=(NodeDefinition(id="ACTIVE"),),
        predicates=(PredicateDefinition(id="ACTIVE_WINDOW", node_ids=("ACTIVE",)),),
        semantic_facts=(
            FactBinding(
                fact=SemanticFact(
                    "strike",
                    "OFFENSE",
                    channels=("STRIKE",),
                    effect_templates=(EffectTemplate("combat.damage", "DAMAGE", 30, "SUM"),),
                ),
                when_predicate="ACTIVE_WINDOW",
                hit_policy=HitPolicy("ONCE_PER_ACTION_INSTANCE", "ON_IMPACT"),
            ),
        ),
    )


def _materialize_rule() -> InteractionRule:
    return InteractionRule(
        "materialize",
        "MATERIALIZATION",
        100,
        {"literal": True},
        (RuleOperation("MATERIALIZE"),),
    )


def test_typed_interaction_pipeline_reduces_commits_and_receipts_once():
    executor = TickExecutor((_typed_definition(),), interaction_rules=(_materialize_rule(),))
    initial = executor.initial_state(resource_banks={"2": {"hp": 100}})
    start = TickInput("start", 1, 0, "START", 0, action_definition_id="TYPED_STRIKE")
    first = Contact("c1", 1, 2, "strike", source_entity_id=1, contact_id="a")
    duplicate = Contact("c2", 1, 2, "strike", source_entity_id=1, contact_id="b")
    state, trace = executor.tick(initial, (start,), HostSnapshot(contacts=(duplicate, first)))
    assert state.resource_banks["2"]["hp"] == 70
    assert len(state.interaction_ledgers) == 1
    assert trace["active_semantic_facts"] == ["1:ACTIVE_WINDOW", "1:strike"]
    assert [item["accepted"] for item in trace["decision_record_mutations"]] == [True, False]
    assert trace["effect_reduction"][0]["value"] == 30


def test_contact_enumeration_permutation_produces_identical_state_digest():
    executor = TickExecutor((_typed_definition(),), interaction_rules=(_materialize_rule(),))
    initial = executor.initial_state(resource_banks={"2": {"hp": 100}})
    start = TickInput("start", 1, 0, "START", 0, action_definition_id="TYPED_STRIKE")
    first = Contact("c1", 1, 2, "strike", source_entity_id=1, contact_id="a")
    duplicate = Contact("c2", 1, 2, "strike", source_entity_id=1, contact_id="b")
    left, left_trace = executor.tick(initial, (start,), HostSnapshot(contacts=(first, duplicate)))
    right, right_trace = executor.tick(initial, (start,), HostSnapshot(contacts=(duplicate, first)))
    assert left.to_snapshot() == right.to_snapshot()
    assert left_trace["state_digest"] == right_trace["state_digest"]


def test_competing_action_starts_reserve_resource_and_slot_atomically():
    definition = ActionDefinition(
        id="SLOTTED",
        rate_scale=1,
        units_per_tick=0,
        nodes=(NodeDefinition(id="RUN"),),
        start_claims=(Claim("RESOURCE", "STAMINA", 7),),
        slot_claims=(Claim("ACTION_SLOT", "FULL_BODY"),),
    )
    executor = TickExecutor((definition,))
    initial = executor.initial_state(
        resource_banks={"1": {"STAMINA": 10}},
        slot_capacities={"1": {"FULL_BODY": 1}},
    )
    later = TickInput("later", 1, 2, "START", 0, action_definition_id="SLOTTED")
    earlier = TickInput("earlier", 1, 1, "START", 0, action_definition_id="SLOTTED")
    state, trace = executor.tick(initial, (later, earlier))
    assert list(state.action_instances) == ["1"]
    assert state.resource_banks["1"]["STAMINA"] == 3
    assert state.action_slots["1"]["FULL_BODY"] == {
        "capacity": 1,
        "instance_ids": [1],
        "usage": 1,
    }
    assert [item["accepted"] for item in trace["pre_advance_intents"]] == [True, False]


def _replacement_definitions() -> tuple[ActionDefinition, ActionDefinition]:
    target = ActionDefinition(
        id="DODGE",
        rate_scale=1,
        units_per_tick=0,
        nodes=(NodeDefinition(id="DODGING"),),
        start_claims=(Claim("RESOURCE", "STAMINA", 5),),
        slot_claims=(Claim("ACTION_SLOT", "FULL_BODY"),),
    )
    source = ActionDefinition(
        id="SOURCE",
        rate_scale=1,
        units_per_tick=0,
        nodes=(NodeDefinition(id="WAIT"),),
        slot_claims=(Claim("ACTION_SLOT", "FULL_BODY"),),
        transitions=(
            TransitionDefinition(
                id="replace_with_dodge",
                source_node="WAIT",
                evaluation_point="PRE_ADVANCE",
                priority=10,
                target_kind="ACTION",
                target_action="DODGE",
                source_disposition="TERMINATE_SOURCE",
                input_command="REPLACE",
            ),
        ),
    )
    return source, target


def test_slot_replacement_does_not_terminate_source_when_target_claims_fail():
    executor = TickExecutor(_replacement_definitions())
    state = executor.initial_state(
        resource_banks={"1": {"STAMINA": 4}},
        slot_capacities={"1": {"FULL_BODY": 1}},
    )
    state, _ = executor.tick(
        state,
        (TickInput("start", 1, 0, "START", 0, action_definition_id="SOURCE"),),
    )
    state, trace = executor.tick(state, (TickInput("replace", 1, 1, "REPLACE", 1),))
    assert state.action_instances["1"].lifecycle_state == "RUNNING"
    assert len(state.action_instances) == 1
    assert state.resource_banks["1"]["STAMINA"] == 4
    assert trace["pre_advance_intents"][0]["accepted"] is False


def test_slot_replacement_starts_target_and_terminates_source_atomically():
    executor = TickExecutor(_replacement_definitions())
    state = executor.initial_state(
        resource_banks={"1": {"STAMINA": 5}},
        slot_capacities={"1": {"FULL_BODY": 1}},
    )
    state, _ = executor.tick(
        state,
        (TickInput("start", 1, 0, "START", 0, action_definition_id="SOURCE"),),
    )
    state, trace = executor.tick(state, (TickInput("replace", 1, 1, "REPLACE", 1),))
    assert state.action_instances["1"].lifecycle_state == "TERMINATED"
    assert state.action_instances["2"].current_node_id == "DODGING"
    assert state.resource_banks["1"]["STAMINA"] == 0
    assert state.action_slots["1"]["FULL_BODY"]["instance_ids"] == [2]
    assert trace["pre_advance_intents"][0]["accepted"] is True


def _parent_child_definitions() -> tuple[ActionDefinition, ActionDefinition]:
    child = ActionDefinition(
        id="CHILD",
        rate_scale=1,
        units_per_tick=0,
        nodes=(NodeDefinition(id="CHILD_RUN"),),
        transitions=(
            TransitionDefinition(
                id="finish_child",
                source_node="CHILD_RUN",
                evaluation_point="PRE_ADVANCE",
                priority=20,
                target_kind="TERMINATE",
                input_command="FINISH",
            ),
        ),
    )
    parent = ActionDefinition(
        id="PARENT",
        rate_scale=1,
        units_per_tick=1,
        nodes=(NodeDefinition(id="PARENT_RUN"), NodeDefinition(id="COMPLETE")),
        child_slot_capacities={"SUB": 1},
        child_termination_policies={"SUB": "TERMINATE_CHILD"},
        transitions=(
            TransitionDefinition(
                id="launch_child",
                source_node="PARENT_RUN",
                evaluation_point="PRE_ADVANCE",
                priority=20,
                target_kind="CHILD_ACTION",
                target_action="CHILD",
                child_slot_id="SUB",
                parent_policy="FREEZE_PROGRESSION",
                input_command="LAUNCH_CHILD",
            ),
            TransitionDefinition(
                id="receive_child_result",
                source_node="PARENT_RUN",
                evaluation_point="PRE_ADVANCE",
                priority=10,
                target_kind="NODE",
                target_node="COMPLETE",
                event_type="CHILD_RESULT",
            ),
            TransitionDefinition(
                id="stop_parent",
                source_node="PARENT_RUN",
                evaluation_point="PRE_ADVANCE",
                priority=30,
                target_kind="TERMINATE",
                input_command="STOP",
            ),
        ),
    )
    return parent, child


def test_parent_child_freeze_result_event_and_restore_equivalence():
    executor = TickExecutor(_parent_child_definitions())
    state = executor.initial_state()
    state, _ = executor.tick(
        state,
        (TickInput("start-parent", 1, 0, "START", 0, action_definition_id="PARENT"),),
    )
    state, _ = executor.tick(state, (TickInput("launch", 1, 1, "LAUNCH_CHILD", 1),))
    assert state.action_instances["1"].child_instance_ids == (2,)
    assert state.action_instances["2"].parent_instance_id == 1
    assert state.action_instances["2"].parent_slot_id == "SUB"
    assert state.action_instances["1"].freeze_token_references == (1,)
    assert state.action_instances["1"].local_step == 2

    snapshot = executor.save(state)
    restored = executor.restore(snapshot)
    assert restored.to_snapshot() == state.to_snapshot()

    def finish_from(current):
        current, _ = executor.tick(current)
        assert current.action_instances["1"].local_step == 2
        current, _ = executor.tick(current, (TickInput("finish", 1, 2, "FINISH", 3),))
        assert current.action_instances["1"].child_instance_ids == ()
        assert current.freeze_tokens == ()
        assert current.pending_events[0]["event_type"] == "CHILD_RESULT"
        current, trace = executor.tick(current)
        assert trace["events_delivered"] == ["child-result:2:1"]
        assert current.action_instances["1"].current_node_id == "COMPLETE"
        assert current.action_instances["1"].local_step == 3
        return current, trace

    direct, direct_trace = finish_from(state)
    replayed, replayed_trace = finish_from(restored)
    assert direct.to_snapshot() == replayed.to_snapshot()
    assert direct_trace["state_digest"] == replayed_trace["state_digest"]


def test_parent_termination_policy_terminates_occupied_child():
    executor = TickExecutor(_parent_child_definitions())
    state = executor.initial_state()
    state, _ = executor.tick(
        state,
        (TickInput("start-parent", 1, 0, "START", 0, action_definition_id="PARENT"),),
    )
    state, _ = executor.tick(state, (TickInput("launch", 1, 1, "LAUNCH_CHILD", 1),))
    state, _ = executor.tick(state, (TickInput("stop", 1, 2, "STOP", 2),))
    assert state.action_instances["1"].lifecycle_state == "TERMINATED"
    assert state.action_instances["2"].lifecycle_state == "TERMINATED"
    assert state.action_instances["1"].child_instance_ids == ()
    assert state.action_instances["1"].freeze_token_references == ()
    assert state.pending_events[0]["event_type"] == "CHILD_RESULT"


def test_max_actions_per_entity_is_enforced_for_slotless_actions():
    definition = ActionDefinition("LIMITED", 1, 0, (NodeDefinition("RUN"),))
    executor = TickExecutor((definition,), RuntimeProfile(max_actions_per_entity=1))
    inputs = tuple(
        TickInput(f"start-{index}", 1, index, "START", 0, action_definition_id="LIMITED")
        for index in range(3)
    )
    state, trace = executor.tick(executor.initial_state(), inputs)
    assert len(state.action_instances) == 1
    assert [item["accepted"] for item in trace["pre_advance_intents"]] == [True, False, False]


def test_terminate_parent_applies_old_child_policy_but_exempts_new_child():
    child = ActionDefinition(
        id="TERMINATE_CHILD_CASE",
        rate_scale=1,
        units_per_tick=0,
        nodes=(NodeDefinition(id="RUN"),),
    )
    parent = ActionDefinition(
        id="TERMINATE_PARENT_CASE",
        rate_scale=1,
        units_per_tick=0,
        nodes=(NodeDefinition(id="RUN"),),
        child_slot_capacities={"SUB": 2},
        child_termination_policies={"SUB": "TERMINATE_CHILD"},
        default_buffer_lifetime=2,
        transitions=(
            TransitionDefinition(
                id="first-child",
                source_node="RUN",
                evaluation_point="PRE_ADVANCE",
                priority=20,
                input_command="FIRST",
                target_kind="CHILD_ACTION",
                target_action=child.id,
                child_slot_id="SUB",
                parent_policy="CONTINUE",
            ),
            TransitionDefinition(
                id="terminating-child",
                source_node="RUN",
                evaluation_point="PRE_ADVANCE",
                priority=10,
                input_command="SECOND",
                target_kind="CHILD_ACTION",
                target_action=child.id,
                child_slot_id="SUB",
                parent_policy="TERMINATE_PARENT",
            ),
        ),
    )
    executor = TickExecutor((parent, child))
    state = executor.initial_state()
    state, _ = executor.tick(
        state,
        (TickInput("start", 1, 0, "START", 0, action_definition_id=parent.id),),
    )
    state, _ = executor.tick(state, (TickInput("first", 1, 1, "FIRST", 1),))
    assert state.action_instances["2"].lifecycle_state == "RUNNING"

    state, _ = executor.tick(state, (TickInput("second", 1, 2, "SECOND", 2),))
    assert state.action_instances["1"].lifecycle_state == "TERMINATED"
    assert state.action_instances["2"].lifecycle_state == "TERMINATED"
    assert state.action_instances["3"].lifecycle_state == "RUNNING"
    assert state.action_instances["1"].child_instance_ids == (3,)
    assert [event["payload"]["child_instance_id"] for event in state.pending_events] == [2]
