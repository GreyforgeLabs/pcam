from dataclasses import replace

import pytest

from pcam_runtime import (
    ActionDefinition,
    ActionInstance,
    BufferEntry,
    Contact,
    Effect,
    HostSnapshot,
    NodeDefinition,
    PCAMError,
    RuntimeProfile,
    TickExecutor,
    TickInput,
)


def _definition(buffer_capacity=1, child_capacity=None):
    child_capacities = {} if child_capacity is None else {"child": child_capacity}
    child_policies = {} if child_capacity is None else {"child": "DETACH_CHILD"}
    return ActionDefinition(
        id="BOUNDED",
        rate_scale=1,
        units_per_tick=0,
        nodes=(NodeDefinition("RUN"),),
        buffer_capacity=buffer_capacity,
        child_slot_capacities=child_capacities,
        child_termination_policies=child_policies,
    )


def _action(instance_id, definition, parent=None, children=(), buffer=()):
    return ActionInstance(
        instance_id=instance_id,
        owner_entity_id=1,
        definition_hash=definition.definition_hash,
        current_node_id="RUN",
        current_rate_units=0,
        parent_instance_id=parent,
        child_instance_ids=children,
        input_buffer=buffer,
    )


def test_definition_size_and_declared_collection_caps_are_enforced():
    with pytest.raises(PCAMError):
        TickExecutor((_definition(),), RuntimeProfile(max_definition_size_bytes=1))
    with pytest.raises(PCAMError):
        TickExecutor((_definition(buffer_capacity=2),), RuntimeProfile(max_buffer_entries_per_action=1))
    with pytest.raises(PCAMError):
        TickExecutor((_definition(child_capacity=2),), RuntimeProfile(max_children_per_action=1))


def test_snapshot_byte_limit_is_enforced_on_save_and_restore():
    executor = TickExecutor((_definition(),), RuntimeProfile(max_snapshot_size_bytes=1))
    state = executor.initial_state()
    with pytest.raises(PCAMError):
        executor.save(state)
    with pytest.raises(PCAMError):
        executor.restore(state.to_snapshot())


def test_untrusted_tick_input_batch_has_a_pre_ingestion_byte_ceiling():
    executor = TickExecutor((_definition(),), RuntimeProfile(max_snapshot_size_bytes=4096))
    oversized = TickInput(
        "oversized",
        1,
        1,
        "PAYLOAD",
        0,
        payload={"value": "x" * 5000},
    )
    with pytest.raises(PCAMError):
        executor.tick(executor.initial_state(), (oversized,))


def test_restored_action_buffer_and_event_counts_are_bounded():
    definition = _definition()
    executor = TickExecutor(
        (definition,),
        RuntimeProfile(
            max_actions_per_entity=1,
            max_buffer_entries_per_action=1,
            max_pending_events_per_entity=1,
        ),
    )
    base = executor.initial_state()
    too_many_actions = replace(
        base,
        action_instances={
            "1": _action(1, definition),
            "2": _action(2, definition),
        },
    )
    with pytest.raises(PCAMError):
        executor.save(too_many_actions)

    tick_input = TickInput("input", 1, 1, "GO", 0)
    entry = BufferEntry.capture(tick_input, lifetime=2)
    too_many_buffers = replace(
        base,
        action_instances={"1": _action(1, definition, buffer=(entry, replace(entry, buffer_entry_id="buffer:2", input_id="2")))},
    )
    with pytest.raises(PCAMError):
        executor.save(too_many_buffers)

    event = {
        "event_id": "e1",
        "event_type": "NOTICE",
        "source_id": 1,
        "target_id": 2,
        "origin_tick": 0,
        "delivery_tick": 1,
        "payload": {},
        "delivery_mode": "TARGET_ENTITY",
    }
    too_many_events = replace(base, pending_events=(event, {**event, "event_id": "e2"}))
    with pytest.raises(PCAMError):
        executor.save(too_many_events)


def test_child_count_nesting_depth_and_parent_cycles_are_bounded():
    definition = _definition()
    executor = TickExecutor(
        (definition,),
        RuntimeProfile(max_children_per_action=1, max_action_nesting_depth=1),
    )
    base = executor.initial_state()
    too_many_children = replace(
        base,
        action_instances={
            "1": _action(1, definition, children=(2, 3)),
            "2": _action(2, definition, parent=1),
            "3": _action(3, definition, parent=1),
        },
    )
    with pytest.raises(PCAMError):
        executor.save(too_many_children)

    too_deep = replace(
        base,
        action_instances={
            "1": _action(1, definition, children=(2,)),
            "2": _action(2, definition, parent=1, children=(3,)),
            "3": _action(3, definition, parent=2),
        },
    )
    with pytest.raises(PCAMError) as raised:
        executor.save(too_deep)
    assert raised.value.fault.value == "NESTING_LIMIT_EXCEEDED"

    cyclic = replace(
        base,
        action_instances={
            "1": _action(1, definition, parent=2),
            "2": _action(2, definition, parent=1),
        },
    )
    with pytest.raises(PCAMError):
        executor.save(cyclic)


def test_candidate_and_effect_counts_are_enforced_at_tick_boundary():
    definition = _definition()
    candidate_executor = TickExecutor((definition,), RuntimeProfile(max_candidates_per_tick=0))
    with pytest.raises(PCAMError):
        candidate_executor.tick(
            candidate_executor.initial_state(),
            host=HostSnapshot(contacts=(Contact("candidate", 999, 2, "NONE"),)),
        )

    effect_executor = TickExecutor((definition,), RuntimeProfile(max_effects_per_tick=0))
    state = effect_executor.initial_state()
    start = TickInput("start", 1, 0, "START", 0, action_definition_id=definition.id)
    state, _ = effect_executor.tick(state, (start,))
    contact = Contact(
        "candidate",
        1,
        2,
        "LEGACY",
        effect=Effect("damage", target_entity_id=2, amount=-1),
    )
    with pytest.raises(PCAMError):
        effect_executor.tick(state, host=HostSnapshot(contacts=(contact,)))
