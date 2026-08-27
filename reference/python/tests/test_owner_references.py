from dataclasses import replace

from pcam_runtime import (
    ActionDefinition,
    NodeDefinition,
    PredicateDefinition,
    TickExecutor,
    TickInput,
)


def test_owner_resource_and_register_references_are_authoritative_and_restorable():
    expression = {
        "op": "and",
        "args": [
            {"op": "gte", "args": [{"ref": "owner.resource.stamina"}, {"literal": 5}]},
            {"op": "eq", "args": [{"ref": "owner.register.stance"}, {"literal": "READY"}]},
        ],
    }
    definition = ActionDefinition(
        "OWNER_REFS",
        1,
        0,
        (NodeDefinition("RUN"),),
        predicates=(PredicateDefinition("READY", expression=expression),),
    )
    executor = TickExecutor((definition,))
    state = executor.initial_state(resource_banks={"1": {"stamina": 5}})
    state = replace(
        state,
        entity_records={"1": {"entity_registers": {"stance": "READY"}}},
    )
    start = TickInput("start", 1, 0, "START", 0, action_definition_id="OWNER_REFS")

    state, trace = executor.tick(state, (start,))

    assert trace["active_semantic_facts"] == ["1:READY"]
    assert state.action_instances["1"].predicate_truth_state == {"READY": True}
    assert executor.restore(executor.save(state)) == state
