"""Typed immutable model records for the PCAM v3 reference slice."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from .canonical import canonical_hash
from .errors import PCAMError, PCAMFault, ResultCode
from .interactions import SemanticFact
from .intents import Claim
from .ledgers import HitPolicy

CANONICAL_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")


@dataclass(frozen=True)
class RuntimeProfile:
    max_actions_per_entity: int = 8
    max_action_nesting_depth: int = 4
    max_children_per_action: int = 4
    max_quanta_per_action_per_tick: int = 8
    max_internal_transitions_per_action_per_tick: int = 8
    max_buffer_entries_per_action: int = 8
    max_pending_events_per_entity: int = 8
    max_candidates_per_tick: int = 32
    max_effects_per_tick: int = 32
    max_redirects_per_candidate: int = 4
    max_definition_size_bytes: int = 65536
    max_snapshot_size_bytes: int = 262144
    max_extension_state_bytes: int = 4096
    fault_policy: str = "ABORT_SIMULATION"


@dataclass(frozen=True)
class NodeDefinition:
    id: str
    mode: Literal["TIMED", "EVENT_DRIVEN", "TERMINAL"] = "EVENT_DRIVEN"
    duration_quanta: int | None = None
    seekable: bool = False
    predicates: tuple[str, ...] = ()


@dataclass(frozen=True)
class PredicateDefinition:
    id: str
    node_ids: tuple[str, ...] = ()
    min_node_step: int = 0
    max_node_step_exclusive: int | None = None


@dataclass(frozen=True)
class TransitionDefinition:
    id: str
    source_node: str
    evaluation_point: Literal["PRE_ADVANCE", "AFTER_QUANTUM", "POST_ADVANCE"]
    priority: int
    target_kind: Literal["NODE", "ACTION", "CHILD_ACTION", "TERMINATE", "FAULT"] = "NODE"
    target_node: str | None = None
    target_action: str | None = None
    source_disposition: Literal["TERMINATE_SOURCE", "SUSPEND_SOURCE", "KEEP_SOURCE"] = "TERMINATE_SOURCE"
    child_slot_id: str | None = None
    parent_policy: str | None = None
    event_type: str | None = None
    target_step: int = 0
    guard_predicate: str | None = None
    input_command: str | None = None
    consume_policy: Literal["ON_ACCEPT", "ON_ATTEMPT", "NEVER"] = "ON_ACCEPT"
    claims: tuple[Claim, ...] = ()
    effects: tuple["Effect", ...] = ()


@dataclass(frozen=True)
class Effect:
    id: str
    kind: Literal["RESOURCE_DELTA", "EVENT"] = "RESOURCE_DELTA"
    effect_class: str = "RESOURCE"
    source_entity_id: int = 0
    target_entity_id: int = 0
    source_action_instance_id: int = 0
    origin_tick: int = 0
    resource: str = "hp"
    amount: int = 0
    priority: int = 0


@dataclass(frozen=True)
class FactBinding:
    fact: SemanticFact
    when_predicate: str
    hit_policy: HitPolicy


@dataclass(frozen=True)
class ActionDefinition:
    id: str
    rate_scale: int
    units_per_tick: int
    nodes: tuple[NodeDefinition, ...]
    predicates: tuple[PredicateDefinition, ...] = ()
    semantic_facts: tuple[FactBinding, ...] = ()
    transitions: tuple[TransitionDefinition, ...] = ()
    start_claims: tuple[Claim, ...] = ()
    slot_claims: tuple[Claim, ...] = ()
    child_slot_capacities: dict[str, int] = field(default_factory=dict)
    child_termination_policies: dict[str, str] = field(default_factory=dict)
    buffer_capacity: int = 8
    buffer_overflow_policy: Literal["DROP_OLDEST", "DROP_NEWEST", "FAULT"] = "DROP_OLDEST"
    default_buffer_lifetime: int = 1
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def definition_hash(self) -> str:
        return canonical_hash(self.to_canonical())

    def to_canonical(self) -> dict[str, object]:
        return {
            "id": self.id,
            "metadata": self.metadata,
            "nodes": [node.__dict__ for node in self.nodes],
            "predicates": [predicate.__dict__ for predicate in self.predicates],
            "semantic_facts": self.semantic_facts,
            "start_claims": self.start_claims,
            "slot_claims": self.slot_claims,
            "child_slot_capacities": self.child_slot_capacities,
            "child_termination_policies": self.child_termination_policies,
            "rate": {"scale": self.rate_scale, "units_per_tick": self.units_per_tick},
            "buffer": {
                "capacity": self.buffer_capacity,
                "default_lifetime": self.default_buffer_lifetime,
                "overflow_policy": self.buffer_overflow_policy,
            },
            "transitions": [
                {
                    **transition.__dict__,
                    "effects": [effect.__dict__ for effect in transition.effects],
                }
                for transition in self.transitions
            ],
        }


@dataclass(frozen=True)
class TickInput:
    input_id: str
    source_entity_id: int
    sequence: int
    command_id: str
    assigned_tick: int
    payload: dict[str, object] = field(default_factory=dict)
    action_definition_id: str | None = None


@dataclass(frozen=True)
class Contact:
    candidate_id: str
    source_instance_id: int
    target_entity_id: int
    fact_id: str
    effect: Effect | None = None
    source_entity_id: int = 0
    contact_partition: str = "default"
    contact_id: str = "contact"
    host_context: dict[str, object] = field(default_factory=dict)
    defense_fact_id: str | None = None


@dataclass(frozen=True)
class HostSnapshot:
    contacts: tuple[Contact, ...] = ()
    imports: dict[str, object] = field(default_factory=dict)


def validate_definition(definition: ActionDefinition) -> None:
    ids = [definition.id]
    ids.extend(node.id for node in definition.nodes)
    ids.extend(predicate.id for predicate in definition.predicates)
    ids.extend(transition.id for transition in definition.transitions)
    for value in ids:
        if not CANONICAL_ID.match(value):
            raise PCAMError(
                ResultCode.DEFINITION_REJECTED,
                PCAMFault.INVALID_CANONICAL_IDENTIFIER,
                value,
            )
    if definition.rate_scale <= 0:
        raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.DIVISION_BY_ZERO, definition.id)
    if definition.units_per_tick < 0:
        raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.INTEGER_OVERFLOW, definition.id)
    if definition.buffer_capacity < 0 or definition.default_buffer_lifetime <= 0:
        raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.STATE_INVARIANT_FAILURE, definition.id)
    if any(capacity <= 0 for capacity in definition.child_slot_capacities.values()):
        raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.STATE_INVARIANT_FAILURE, definition.id)
    if set(definition.child_termination_policies) != set(definition.child_slot_capacities):
        raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.STATE_INVARIANT_FAILURE, definition.id)
    node_ids = {node.id for node in definition.nodes}
    predicate_ids = {predicate.id for predicate in definition.predicates}
    if not definition.nodes:
        raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.STATE_INVARIANT_FAILURE, "action has no nodes")
    for node in definition.nodes:
        if node.mode == "TIMED" and (node.duration_quanta is None or node.duration_quanta <= 0):
            raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.STATE_INVARIANT_FAILURE, node.id)
        if node.mode != "TIMED" and node.duration_quanta is not None:
            raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.STATE_INVARIANT_FAILURE, node.id)
    fact_ids: set[str] = set()
    for binding in definition.semantic_facts:
        if binding.fact.fact_id in fact_ids:
            raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.STATE_INVARIANT_FAILURE, binding.fact.fact_id)
        fact_ids.add(binding.fact.fact_id)
        if binding.when_predicate not in predicate_ids:
            raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.MISSING_REFERENCE, binding.when_predicate)
    seen_priorities: set[tuple[str, str, int]] = set()
    for transition in definition.transitions:
        if transition.evaluation_point == "AFTER_QUANTUM" and transition.claims:
            raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.STATE_INVARIANT_FAILURE, transition.id)
        if transition.source_node not in node_ids:
            raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.STATE_INVARIANT_FAILURE, transition.source_node)
        if transition.target_kind == "NODE":
            if transition.target_node not in node_ids:
                raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.STATE_INVARIANT_FAILURE, str(transition.target_node))
            target = next(node for node in definition.nodes if node.id == transition.target_node)
            if transition.target_step and not target.seekable:
                raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.STATE_INVARIANT_FAILURE, target.id)
            if target.mode == "TIMED" and target.duration_quanta is not None and transition.target_step >= target.duration_quanta:
                raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.STATE_INVARIANT_FAILURE, target.id)
        if transition.target_kind == "CHILD_ACTION":
            if transition.child_slot_id not in definition.child_slot_capacities:
                raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.MISSING_REFERENCE, str(transition.child_slot_id))
            if transition.parent_policy not in {
                "CONTINUE",
                "FREEZE_PROGRESSION",
                "FREEZE_TRANSITIONS",
                "FREEZE_ALL_ACTION_LOGIC",
                "TERMINATE_PARENT",
            }:
                raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.STATE_INVARIANT_FAILURE, transition.id)
        if transition.guard_predicate is not None and transition.guard_predicate not in predicate_ids:
            raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.STATE_INVARIANT_FAILURE, transition.guard_predicate)
        key = (transition.source_node, transition.evaluation_point, transition.priority)
        if key in seen_priorities:
            raise PCAMError(
                ResultCode.DEFINITION_REJECTED,
                PCAMFault.DUPLICATE_TRANSITION_PRIORITY,
                transition.id,
            )
        seen_priorities.add(key)
