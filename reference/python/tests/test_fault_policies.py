from dataclasses import replace

import pytest

from pcam_runtime import (
    ActionDefinition,
    Assignment,
    DefinitionEffect,
    NodeDefinition,
    PCAMError,
    RuntimeProfile,
    TickExecutor,
    TickInput,
    TransitionDefinition,
)


def _executor(policy):
    definition = ActionDefinition("FAULTABLE", 1, 0, (NodeDefinition("RUN"),))
    profile = RuntimeProfile(
        fault_policy=policy,
        max_quanta_per_action_per_tick=1,
    )
    return TickExecutor((definition,), profile)


def _start(owner, sequence=0):
    return TickInput(
        f"start-{owner}-{sequence}",
        owner,
        sequence,
        "START",
        0,
        action_definition_id="FAULTABLE",
    )


def _set_rate(state, instance_id, rate):
    actions = dict(state.action_instances)
    actions[str(instance_id)] = replace(actions[str(instance_id)], current_rate_units=rate)
    return replace(state, action_instances=actions)


def test_fault_action_restores_tick_start_and_faults_only_the_initiating_action():
    executor = _executor("FAULT_ACTION")
    state, _ = executor.tick(executor.initial_state(), (_start(1), _start(2)))
    state = _set_rate(state, 1, 2)
    before = state.to_snapshot()

    state, trace = executor.tick(state)

    assert state.tick == 2
    assert state.action_instances["1"].lifecycle_state == "FAULTED"
    assert state.action_instances["1"].fault_record == "QUANTUM_LIMIT_EXCEEDED"
    assert state.action_instances["2"].lifecycle_state == "RUNNING"
    assert state.action_instances["2"].local_step == before["action_instances"][1]["local_step"]
    assert trace["faults"] == [state.fault_state["last_fault"]]
    assert trace["faults"][0]["policy"] == "FAULT_ACTION"
    assert trace["faults"][0]["action_instance_id"] == 1
    assert trace["typed_effects_emitted"] == []
    assert executor.restore(executor.save(state)) == state


def test_fault_entity_faults_all_owner_actions_and_preserves_other_entities():
    executor = _executor("FAULT_ENTITY")
    state, _ = executor.tick(
        executor.initial_state(),
        (_start(1, 0), _start(1, 1), _start(2, 0)),
    )
    state = _set_rate(state, 1, 2)
    actions = dict(state.action_instances)
    actions["1"] = replace(actions["1"], parent_instance_id=3, parent_slot_id="cross")
    actions["3"] = replace(actions["3"], child_instance_ids=(1,))
    state = replace(state, action_instances=actions)

    state, trace = executor.tick(state)

    assert state.tick == 2
    assert [state.action_instances[key].lifecycle_state for key in ("1", "2", "3")] == [
        "FAULTED",
        "FAULTED",
        "RUNNING",
    ]
    assert state.entity_records["1"]["fault_record"] == state.fault_state["last_fault"]
    assert state.action_instances["1"].parent_instance_id is None
    assert state.action_instances["1"].parent_slot_id is None
    assert state.action_instances["3"].child_instance_ids == ()
    assert trace["faults"][0]["owner_entity_id"] == 1
    assert trace["faults"][0]["policy"] == "FAULT_ENTITY"


def test_fault_entity_contains_a_direct_start_fault_without_an_action_instance():
    assignment = Assignment("action.register.counter", {"literal": 2})
    definition = ActionDefinition(
        "BAD_START",
        1,
        0,
        (NodeDefinition("DONE", "TERMINAL", entry_assignments=(assignment,)),),
        register_initials={"counter": 0},
        register_declarations={
            "counter": {
                "type": "U64",
                "minimum": 0,
                "maximum": 1,
                "overflow": "FAULT",
            }
        },
    )
    executor = TickExecutor((definition,), RuntimeProfile(fault_policy="FAULT_ENTITY"))
    start = TickInput("bad-start", 4, 0, "START", 0, action_definition_id="BAD_START")

    state, trace = executor.tick(executor.initial_state(), (start,))

    assert state.tick == 1
    assert state.action_instances == {}
    assert state.entity_records["4"]["fault_record"]["fault"] == "INTEGER_OVERFLOW"
    assert trace["faults"][0]["action_instance_id"] is None
    assert trace["faults"][0]["owner_entity_id"] == 4


def test_unattributable_fault_escalates_to_abort_behavior():
    executor = _executor("FAULT_ACTION")
    initial = executor.initial_state()
    mismatched = replace(initial, definition_set_hash="0" * 64)

    with pytest.raises(PCAMError) as raised:
        executor.tick(mismatched)

    assert raised.value.fault.value == "SNAPSHOT_DEFINITION_MISMATCH"
    state, trace, error = executor.tick_with_fault_trace(mismatched)
    assert error is not None
    assert state == mismatched
    assert trace["state_digest"] == mismatched.state_hash()


def test_containment_discards_mutations_and_effects_emitted_before_the_fault():
    emitter = ActionDefinition(
        "EMITTER",
        1,
        0,
        (NodeDefinition("RUN", "TIMED", 1), NodeDefinition("DONE")),
        transitions=(
            TransitionDefinition(
                "emit",
                "RUN",
                "AFTER_QUANTUM",
                1,
                target_node="DONE",
                definition_effects=(
                    DefinitionEffect("presentation.flash", False, {"literal": "flash"}),
                ),
            ),
        ),
    )
    faultable = ActionDefinition("FAULTABLE", 1, 0, (NodeDefinition("RUN"),))
    executor = TickExecutor(
        (emitter, faultable),
        RuntimeProfile(fault_policy="FAULT_ACTION", max_quanta_per_action_per_tick=1),
    )
    starts = (
        TickInput("start-emitter", 1, 0, "START", 0, action_definition_id="EMITTER"),
        TickInput("start-faultable", 2, 0, "START", 0, action_definition_id="FAULTABLE"),
    )
    state, _ = executor.tick(executor.initial_state(), starts)
    state = _set_rate(state, 1, 1)
    state = _set_rate(state, 2, 2)

    state, trace = executor.tick(state)

    assert state.action_instances["1"].current_node_id == "RUN"
    assert state.action_instances["1"].node_step == 0
    assert state.action_instances["1"].emission_serial == 0
    assert state.action_instances["2"].lifecycle_state == "FAULTED"
    assert trace["typed_effects_emitted"] == []
    assert trace["effects_emitted"] == []
