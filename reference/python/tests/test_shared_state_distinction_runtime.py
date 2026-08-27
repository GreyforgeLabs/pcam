import json
from pathlib import Path

from pcam_runtime import canonical_dumps
from pcam_runtime.vectors import run_vector

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads(
        (ROOT / "tests/vectors/state-distinction-runtime.json").read_text(encoding="utf-8")
    )


def _branch_snapshot(base_snapshot, branch):
    snapshot = json.loads(json.dumps(base_snapshot))
    if "remaining_ticks" in branch:
        snapshot["freeze_tokens"] = [
            {
                "token_id": 1,
                "source_id": 9,
                "target_id": 1,
                "domains": ["PROGRESSION"],
                "remaining_ticks": branch["remaining_ticks"],
                "activation_tick": snapshot["tick"],
                "stack_policy": "INDEPENDENT",
                "stack_group": "state-distinction",
                "accrual_policy": "HOLD",
                "metadata": {"kind": "STALL_COUNTER"},
            }
        ]
        snapshot["next_freeze_token_id"] = 2
    if "cycle" in branch:
        snapshot["action_instances"][0]["cycle"] = branch["cycle"]
    return snapshot


def test_python_equal_phase_stall_and_cycle_states_serialize_hash_and_continue_distinctly():
    vector = _vector()
    run = run_vector(vector)
    base_snapshot = run.final_state.to_snapshot()

    for case in vector["cases"]:
        phases = []
        serializations = []
        initial_digests = []
        summaries = []
        for branch in case["branches"]:
            snapshot = _branch_snapshot(base_snapshot, branch)
            state = run.executor.restore(snapshot)
            action = state.action_instances["1"]
            phases.append((action.current_node_id, action.node_step, action.local_step))
            serializations.append(canonical_dumps(state.to_snapshot()))
            initial_digests.append(state.state_hash())

            tick_state_digests = []
            local_steps = []
            cycles = []
            remaining_ticks = []
            for _ in range(case["continuation_ticks"]):
                state, trace = run.executor.tick(state)
                action = state.action_instances["1"]
                tick_state_digests.append(trace["state_digest"])
                local_steps.append(action.local_step)
                cycles.append(action.cycle)
                remaining_ticks.append(
                    state.freeze_tokens[0].remaining_ticks if state.freeze_tokens else 0
                )
            summary = {
                "initial_state_digest": initial_digests[-1],
                "tick_state_digests": tick_state_digests,
                "local_steps": local_steps,
                "cycles": cycles,
                "remaining_ticks": remaining_ticks,
            }
            assert summary == case["expected"][branch["id"]], branch["id"]
            summaries.append(summary)

        assert phases[0] == phases[1]
        assert serializations[0] != serializations[1]
        assert initial_digests[0] != initial_digests[1]
        if case["id"] == "distinct-stall-counters":
            assert summaries[0]["local_steps"][-1] != summaries[1]["local_steps"][-1]
        else:
            assert summaries[0]["cycles"] != summaries[1]["cycles"]
