import json
from pathlib import Path

import pytest

from pcam_runtime import Contact, HostSnapshot, PCAMError
from pcam_runtime.vectors import run_vector

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads(
        (ROOT / "tests/vectors/effect-fault-runtime.json").read_text(encoding="utf-8")
    )


def _fault_host(vector):
    return HostSnapshot(
        contacts=tuple(
            Contact(
                candidate_id=contact["candidate_id"],
                source_instance_id=contact["source_instance_id"],
                source_entity_id=contact["source_entity_id"],
                target_entity_id=contact["target_entity_id"],
                fact_id=contact["fact_id"],
                contact_id=contact["contact_id"],
            )
            for contact in vector["fault_tick"]["contacts"]
        )
    )


def test_python_effect_fault_discards_tick_and_applies_shared_policy():
    vector = _vector()
    host = _fault_host(vector)
    for case in vector["cases"]:
        document = json.loads(json.dumps(vector))
        document["runtime_profile"]["fault_policy"] = case["policy"]
        run = run_vector(document)
        before = run.final_state
        assert before.state_hash() == case["pre_fault_digest"]

        if case["policy"] == "ABORT_SIMULATION":
            with pytest.raises(PCAMError) as raised:
                run.executor.tick(before, (), host)
            assert raised.value.fault.value == case["fault"]
            assert raised.value.message == case["message"]
            assert raised.value.action_instance_id == case["action_instance_id"]
            assert raised.value.owner_entity_id == case["owner_entity_id"]
            assert before.state_hash() == case["pre_fault_digest"]
            continue

        state, trace = run.executor.tick(before, (), host)
        summary = {
            "tick": state.tick,
            "lifecycle": {
                key: action.lifecycle_state for key, action in state.action_instances.items()
            },
            "fault_records": {
                key: action.fault_record for key, action in state.action_instances.items()
            },
            "entity_fault_owners": sorted(
                int(key) for key, record in state.entity_records.items() if "fault_record" in record
            ),
            "resources": state.resource_banks,
            "trace_faults": trace["faults"],
            "trace_effects": trace["typed_effects_emitted"],
            "ledger_count": len(state.interaction_ledgers),
        }
        assert summary == case["expected"], case["policy"]
        assert state.state_hash() == case["final_state_digest"]
