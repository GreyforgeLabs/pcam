import json
from dataclasses import replace
from pathlib import Path

from pcam_runtime import ActionDefinition, NodeDefinition, PCAMError, RuntimeProfile, TickExecutor
from pcam_runtime.errors import PCAMFault, ResultCode
from pcam_runtime.state import ActionInstance

ROOT = Path(__file__).resolve().parents[3]


def _vectors():
    return json.loads((ROOT / "tests/vectors/fault-containment.json").read_text(encoding="utf-8"))


def _executor(policy):
    definition = ActionDefinition("FAULTABLE", 1, 0, (NodeDefinition("RUN"),))
    return TickExecutor((definition,), RuntimeProfile(fault_policy=policy)), definition


def _state(executor, definition, tick, actions):
    instances = {
        str(value["instance_id"]): ActionInstance(
            instance_id=value["instance_id"],
            owner_entity_id=value["owner_entity_id"],
            definition_hash=definition.definition_hash,
            current_node_id="RUN",
            parent_instance_id=value.get("parent_instance_id"),
            parent_slot_id=value.get("parent_slot_id"),
            child_instance_ids=tuple(value.get("child_instance_ids", ())),
        )
        for value in actions
    }
    return replace(
        executor.initial_state(),
        tick=tick,
        action_instances=instances,
        next_action_instance_id=len(instances) + 1,
    )


def _error(value):
    return PCAMError(
        ResultCode(value["code"]),
        PCAMFault(value["fault"]),
        value["message"],
        value.get("action_instance_id"),
        value.get("owner_entity_id"),
    )


def _projection(state):
    entity_owner = next(
        (int(owner) for owner, record in state.entity_records.items() if "fault_record" in record),
        None,
    )
    return {
        "tick": state.tick,
        "lifecycle": {key: action.lifecycle_state for key, action in state.action_instances.items()},
        "fault_records": {key: action.fault_record for key, action in state.action_instances.items()},
        "parents": {key: action.parent_instance_id for key, action in state.action_instances.items()},
        "children": {key: list(action.child_instance_ids) for key, action in state.action_instances.items()},
        "entity_fault_owner": entity_owner,
    }


def test_python_fault_containment_matches_shared_scope_and_detachment_vectors():
    for case in _vectors()["cases"]:
        executor, definition = _executor(case["policy"])
        initial = _state(executor, definition, case["tick"], case["actions"])
        contained = executor._contain_fault(initial, _error(case["fault"]))  # noqa: SLF001
        assert contained is not None, case["id"]
        state, _ = contained
        assert _projection(state) == case["expected"], case["id"]
        assert state.fault_state["last_fault"]["policy"] == case["policy"]


def test_python_fault_containment_matches_shared_abort_escalation():
    for case in _vectors()["abort_cases"]:
        executor, definition = _executor(case["policy"])
        initial = _state(executor, definition, 0, [])
        assert executor._contain_fault(initial, _error(case["fault"])) is None  # noqa: SLF001
