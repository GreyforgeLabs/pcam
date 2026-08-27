from dataclasses import replace

from pcam_runtime import (
    ActionDefinition,
    Assignment,
    DefinitionEffect,
    EventEnvelope,
    NodeDefinition,
    TickExecutor,
    TickInput,
    TransitionDefinition,
    event_snapshot,
)


def _definition(transition):
    return ActionDefinition(
        "CONTEXT",
        1,
        0,
        (NodeDefinition("RUN"), NodeDefinition("DONE", "TERMINAL")),
        transitions=(transition,),
        register_initials={"value": 0},
        register_declarations={
            "value": {
                "type": "U64",
                "minimum": 0,
                "maximum": 100,
                "overflow": "FAULT",
            }
        },
        default_buffer_lifetime=2,
    )


def _start():
    return TickInput("start", 1, 0, "START", 0, action_definition_id="CONTEXT")


def test_matched_input_context_is_stable_across_guard_assignment_and_effect():
    transition = TransitionDefinition(
        "input",
        "RUN",
        "PRE_ADVANCE",
        1,
        target_node="DONE",
        input_command="GO",
        guard_expression={"op": "eq", "args": [{"ref": "input.payload.power"}, {"literal": 7}]},
        assignments=(Assignment("action.register.value", {"ref": "input.sequence"}),),
        definition_effects=(
            DefinitionEffect("presentation.input", False, {"ref": "input.payload.power"}),
        ),
    )
    executor = TickExecutor((_definition(transition),))
    state, _ = executor.tick(executor.initial_state(), (_start(),))
    go = TickInput("go", 1, 9, "GO", 1, payload={"power": 7})

    state, trace = executor.tick(state, (go,))

    assert state.action_instances["1"].registers == {"value": 9}
    assert trace["typed_effects_emitted"][0]["payload"] == 7


def test_matched_event_context_is_stable_across_guard_assignment_and_effect():
    transition = TransitionDefinition(
        "event",
        "RUN",
        "PRE_ADVANCE",
        1,
        target_node="DONE",
        event_type="READY",
        guard_expression={"ref": "event.payload.allowed"},
        assignments=(Assignment("action.register.value", {"ref": "event.payload.value"}),),
        definition_effects=(
            DefinitionEffect("presentation.event", False, {"ref": "event.event_id"}),
        ),
    )
    executor = TickExecutor((_definition(transition),))
    state, _ = executor.tick(executor.initial_state(), (_start(),))
    event = EventEnvelope("ready", "READY", 99, 1, 0, 1, {"allowed": True, "value": 12}, "TARGET_ACTION")
    state = replace(state, pending_events=(event_snapshot(event),))

    state, trace = executor.tick(state)

    assert state.action_instances["1"].registers == {"value": 12}
    assert trace["typed_effects_emitted"][0]["payload"] == "ready"
