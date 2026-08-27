from dataclasses import replace

from pcam_runtime import ActionDefinition, FreezeToken, NodeDefinition, TickExecutor, TickInput


def _running_state():
    definition = ActionDefinition("STATE_TEST", 1, 1, (NodeDefinition("RUN"),))
    executor = TickExecutor((definition,))
    state = executor.initial_state()
    state, _ = executor.tick(
        state,
        (TickInput("start", 1, 0, "START", 0, action_definition_id="STATE_TEST"),),
    )
    return executor, state


def test_38_1_equal_projection_with_distinct_freeze_state_hashes_and_behaves_differently():
    executor, ordinary = _running_state()
    token = FreezeToken.created(1, 9, 1, creation_tick=0, duration=1, domains=("PROGRESSION",))
    frozen = replace(ordinary, freeze_tokens=(token,))
    assert ordinary.action_instances["1"].current_node_id == frozen.action_instances["1"].current_node_id
    assert ordinary.action_instances["1"].node_step == frozen.action_instances["1"].node_step
    assert ordinary.state_hash() != frozen.state_hash()
    ordinary, _ = executor.tick(ordinary)
    frozen, _ = executor.tick(frozen)
    assert ordinary.action_instances["1"].local_step == frozen.action_instances["1"].local_step + 1


def test_38_2_equal_projection_with_distinct_cycle_hashes_differently():
    _, first_cycle = _running_state()
    action = first_cycle.action_instances["1"]
    later_cycle = replace(first_cycle, action_instances={"1": replace(action, cycle=12)})
    assert first_cycle.action_instances["1"].current_node_id == later_cycle.action_instances["1"].current_node_id
    assert first_cycle.action_instances["1"].node_step == later_cycle.action_instances["1"].node_step
    assert first_cycle.state_hash() != later_cycle.state_hash()
