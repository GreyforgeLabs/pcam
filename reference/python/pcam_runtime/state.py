"""Authoritative state records and complete JSON snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from .canonical import canonical_hash


@dataclass(frozen=True)
class ActionInstance:
    instance_id: int
    owner_entity_id: int
    definition_hash: str
    slot_claims: tuple[dict[str, object], ...] = ()
    lifecycle_state: Literal["PENDING", "RUNNING", "SUSPENDED", "TERMINATED", "FAULTED"] = "RUNNING"
    current_node_id: str = ""
    node_step: int = 0
    local_step: int = 0
    cycle: int = 0
    transition_serial: int = 0
    quantum_accumulator: int = 0
    current_rate_units: int = 0
    captured_parameters: dict[str, object] = field(default_factory=dict)
    input_buffer: tuple[dict[str, object], ...] = ()
    event_inbox: tuple[dict[str, object], ...] = ()
    freeze_token_references: tuple[int, ...] = ()
    parent_instance_id: int | None = None
    parent_slot_id: str | None = None
    child_instance_ids: tuple[int, ...] = ()
    predicate_truth_state: dict[str, bool] = field(default_factory=dict)
    predicate_entry_serials: dict[str, int] = field(default_factory=dict)
    predicate_exit_serials: dict[str, int] = field(default_factory=dict)
    emission_serial: int = 0
    interaction_ledger_partition: str = "default"
    rng_stream_ids: tuple[str, ...] = ()
    registers: dict[str, int] = field(default_factory=dict)
    fault_record: str | None = None
    extension_state: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SimulationState:
    tick: int
    definition_set_hash: str
    entity_records: dict[str, dict[str, object]] = field(default_factory=dict)
    action_instances: dict[str, ActionInstance] = field(default_factory=dict)
    resource_banks: dict[str, dict[str, int]] = field(default_factory=dict)
    action_slots: dict[str, object] = field(default_factory=dict)
    pending_inputs: tuple[dict[str, object], ...] = ()
    input_buffers: dict[str, object] = field(default_factory=dict)
    pending_events: tuple[dict[str, object], ...] = ()
    freeze_tokens: tuple[dict[str, object], ...] = ()
    interaction_ledgers: dict[str, dict[str, object]] = field(default_factory=dict)
    rng_streams: dict[str, object] = field(default_factory=dict)
    next_action_instance_id: int = 1
    next_freeze_token_id: int = 1
    extension_state: dict[str, object] = field(default_factory=dict)
    fault_state: dict[str, object] = field(default_factory=dict)
    host_state: dict[str, object] = field(default_factory=dict)
    def state_hash(self) -> str:
        return canonical_hash(self.to_snapshot())

    def to_snapshot(self) -> dict[str, object]:
        return {
            "pcam_version": "3.0",
            "action_instances": [
                _instance_snapshot(self.action_instances[key])
                for key in sorted(self.action_instances, key=int)
            ],
            "action_slots": self.action_slots,
            "definition_set_hash": self.definition_set_hash,
            "entity_records": self.entity_records,
            "extension_state": self.extension_state,
            "fault_state": self.fault_state,
            "freeze_tokens": list(self.freeze_tokens),
            "host_state": self.host_state,
            "input_buffers": self.input_buffers,
            "interaction_ledgers": self.interaction_ledgers,
            "next_action_instance_id": self.next_action_instance_id,
            "next_freeze_token_id": self.next_freeze_token_id,
            "pending_events": list(self.pending_events),
            "pending_inputs": list(self.pending_inputs),
            "resource_banks": self.resource_banks,
            "rng_streams": self.rng_streams,
            "tick": self.tick,
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, object]) -> "SimulationState":
        if snapshot.get("pcam_version") != "3.0":
            raise ValueError("snapshot pcam_version must be 3.0")
        action_values = snapshot["action_instances"]
        if not isinstance(action_values, list):
            raise ValueError("snapshot action_instances must be an array")
        actions = {}
        for value in action_values:
            if not isinstance(value, dict):
                raise ValueError("snapshot action instance must be an object")
            action = ActionInstance(**value)  # type: ignore[arg-type]
            actions[str(action.instance_id)] = action
        return cls(
            tick=int(snapshot["tick"]),
            definition_set_hash=str(snapshot["definition_set_hash"]),
            entity_records=dict(snapshot.get("entity_records", {})),
            action_instances=actions,
            resource_banks=dict(snapshot.get("resource_banks", {})),
            action_slots=dict(snapshot.get("action_slots", {})),
            pending_inputs=tuple(snapshot.get("pending_inputs", ())),  # type: ignore[arg-type]
            input_buffers=dict(snapshot.get("input_buffers", {})),
            pending_events=tuple(snapshot.get("pending_events", ())),  # type: ignore[arg-type]
            freeze_tokens=tuple(snapshot.get("freeze_tokens", ())),  # type: ignore[arg-type]
            interaction_ledgers=dict(snapshot.get("interaction_ledgers", {})),
            rng_streams=dict(snapshot.get("rng_streams", {})),
            next_action_instance_id=int(snapshot.get("next_action_instance_id", 1)),
            next_freeze_token_id=int(snapshot.get("next_freeze_token_id", 1)),
            extension_state=dict(snapshot.get("extension_state", {})),
            fault_state=dict(snapshot.get("fault_state", {})),
            host_state=dict(snapshot.get("host_state", {})),
        )


def with_action(state: SimulationState, action: ActionInstance) -> SimulationState:
    actions = dict(state.action_instances)
    actions[str(action.instance_id)] = action
    return replace(state, action_instances=actions)


def _instance_snapshot(instance: ActionInstance) -> dict[str, object]:
    return {
        "current_node_id": instance.current_node_id,
        "current_rate_units": instance.current_rate_units,
        "captured_parameters": instance.captured_parameters,
        "child_instance_ids": list(instance.child_instance_ids),
        "cycle": instance.cycle,
        "definition_hash": instance.definition_hash,
        "emission_serial": instance.emission_serial,
        "event_inbox": list(instance.event_inbox),
        "extension_state": instance.extension_state,
        "fault_record": instance.fault_record,
        "freeze_token_references": list(instance.freeze_token_references),
        "instance_id": instance.instance_id,
        "lifecycle_state": instance.lifecycle_state,
        "local_step": instance.local_step,
        "node_step": instance.node_step,
        "owner_entity_id": instance.owner_entity_id,
        "parent_instance_id": instance.parent_instance_id,
        "parent_slot_id": instance.parent_slot_id,
        "predicate_entry_serials": instance.predicate_entry_serials,
        "predicate_exit_serials": instance.predicate_exit_serials,
        "predicate_truth_state": instance.predicate_truth_state,
        "quantum_accumulator": instance.quantum_accumulator,
        "registers": instance.registers,
        "rng_stream_ids": list(instance.rng_stream_ids),
        "slot_claims": list(instance.slot_claims),
        "input_buffer": list(instance.input_buffer),
        "interaction_ledger_partition": instance.interaction_ledger_partition,
        "transition_serial": instance.transition_serial,
    }
