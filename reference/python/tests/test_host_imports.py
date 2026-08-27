from pcam_runtime import (
    ActionDefinition,
    DefinitionEffect,
    HostSnapshot,
    NodeDefinition,
    PredicateDefinition,
    TickExecutor,
    TickInput,
    TransitionDefinition,
)


def _start(definition_id):
    return TickInput("start", 1, 0, "START", 0, action_definition_id=definition_id)


def test_host_import_default_and_supplied_value_drive_guards_and_predicates():
    definition = ActionDefinition(
        "HOST_GUARD",
        1,
        0,
        (NodeDefinition("RUN"), NodeDefinition("DONE", "TERMINAL")),
        predicates=(
            PredicateDefinition("GROUNDED", expression={"ref": "host.grounded"}),
        ),
        transitions=(
            TransitionDefinition(
                "finish",
                "RUN",
                "PRE_ADVANCE",
                1,
                target_node="DONE",
                guard_expression={"ref": "host.grounded"},
            ),
        ),
        import_declarations={
            "grounded": {
                "type": "BOOL",
                "failure_policy": "USE_DEFAULT",
                "default": False,
                "authoritative": True,
                "serialization_dependency": True,
            }
        },
    )
    executor = TickExecutor((definition,))
    state, first = executor.tick(executor.initial_state(), (_start("HOST_GUARD"),))
    assert first["active_semantic_facts"] == []
    assert state.action_instances["1"].current_node_id == "RUN"

    state, trace = executor.tick(state, host=HostSnapshot(imports={"grounded": True}))

    assert trace["selected_transitions"][0]["transition_id"] == "finish"
    assert state.action_instances["1"].lifecycle_state == "TERMINATED"
    assert state.host_state["imports"] == {"grounded": True}


def test_host_import_is_available_to_initial_effect_payloads():
    definition = ActionDefinition(
        "HOST_EFFECT",
        1,
        0,
        (
            NodeDefinition(
                "DONE",
                "TERMINAL",
                entry_effects=(
                    DefinitionEffect("presentation.power", False, {"ref": "host.power"}),
                ),
            ),
        ),
        import_declarations={
            "power": {
                "type": "U64",
                "failure_policy": "FAULT",
                "authoritative": True,
                "serialization_dependency": True,
            }
        },
    )
    executor = TickExecutor((definition,))
    imports = {"power": 7}
    state, trace = executor.tick(
        executor.initial_state(),
        (_start("HOST_EFFECT"),),
        HostSnapshot(imports=imports),
    )
    imports["power"] = 99

    assert trace["typed_effects_emitted"][0]["payload"] == 7
    assert state.host_state["imports"] == {"power": 7}
    assert executor.restore(executor.save(state)) == state


def test_missing_or_invalid_host_import_faults_before_start_allocation():
    definition = ActionDefinition(
        "HOST_REQUIRED",
        1,
        0,
        (
            NodeDefinition(
                "DONE",
                "TERMINAL",
                entry_effects=(
                    DefinitionEffect("presentation.flag", False, {"ref": "host.flag"}),
                ),
            ),
        ),
        import_declarations={
            "flag": {
                "type": "BOOL",
                "failure_policy": "FAULT",
                "authoritative": True,
                "serialization_dependency": True,
            }
        },
    )
    executor = TickExecutor((definition,))
    for host in (HostSnapshot(), HostSnapshot(imports={"flag": 1})):
        initial = executor.initial_state()
        state, _, error = executor.tick_with_fault_trace(
            initial,
            (_start("HOST_REQUIRED"),),
            host,
        )
        assert error is not None
        assert error.fault.value == "INVALID_HOST_IMPORT"
        assert state == initial
        assert state.next_action_instance_id == 1
