"""Minimal 12-stage PCAM logical-tick executor."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from .buffers import BufferEntry, apply_consumption, capture_entry, end_tick as expire_buffers, select_entry
from .canonical import canonical_dumps, canonical_hash
from .effects import EffectEnvelope, reduce_effects
from .errors import PCAMError, PCAMFault, ResultCode
from .events import EventEnvelope, canonical_events, deliver_due, event_from_snapshot, event_snapshot
from .expressions import evaluate
from .extensions import ExtensionRegistry
from .freezes import FreezeToken, add_token, end_tick as expire_freezes, is_frozen, progression_accrual
from .interactions import InteractionCandidate, InteractionRule, SemanticFact, resolve_candidate, validate_rules
from .intents import ArbitrationState, Claim, Intent, IntentDecision, arbitrate
from .ledgers import LedgerContext, is_eligible as ledger_is_eligible, receipt_required, write_receipt
from .model import (
    ActionDefinition,
    Assignment,
    Contact,
    DefinitionEffect,
    Effect,
    FactBinding,
    HostSnapshot,
    RuntimeProfile,
    TickInput,
    TransitionDefinition,
    validate_definition,
)
from .numeric import U64_MAX, add_i64, apply_u64, mul_i64
from .rng import PCG32Stream
from .state import ActionInstance, SimulationState


class TickExecutor:
    def __init__(
        self,
        definitions: tuple[ActionDefinition, ...],
        profile: RuntimeProfile | None = None,
        interaction_rules: tuple[InteractionRule, ...] = (),
        effect_registry: dict[str, tuple[str, int]] | None = None,
        extension_registry: ExtensionRegistry | None = None,
    ):
        self.profile = profile or RuntimeProfile()
        self.extension_registry = extension_registry or ExtensionRegistry()
        self.extension_registry.validate(self.profile.extensions, self.profile.max_extension_state_bytes)
        self.extension_registry.require_executable(
            self.profile.extensions,
            self.profile.max_extension_state_bytes,
        )
        validate_rules(interaction_rules)
        self.interaction_rules = interaction_rules
        self.effect_registry = (
            effect_registry
            if effect_registry is not None
            else {
                "combat.damage": ("hp", -1),
                "combat.stagger": ("stagger", 1),
            }
        )
        for definition in definitions:
            validate_definition(definition)
            if len(canonical_dumps(definition.to_canonical())) > self.profile.max_definition_size_bytes:
                raise PCAMError(
                    ResultCode.DEFINITION_REJECTED,
                    PCAMFault.STATE_INVARIANT_FAILURE,
                    f"definition exceeds max_definition_size_bytes: {definition.id}",
                )
            if definition.buffer_capacity > self.profile.max_buffer_entries_per_action:
                raise PCAMError(
                    ResultCode.DEFINITION_REJECTED,
                    PCAMFault.STATE_INVARIANT_FAILURE,
                    f"buffer capacity exceeds runtime profile: {definition.id}",
                )
            if any(
                capacity > self.profile.max_children_per_action
                for capacity in definition.child_slot_capacities.values()
            ):
                raise PCAMError(
                    ResultCode.DEFINITION_REJECTED,
                    PCAMFault.STATE_INVARIANT_FAILURE,
                    f"child slot capacity exceeds runtime profile: {definition.id}",
                )
            self.extension_registry.validate(definition.extensions, self.profile.max_extension_state_bytes)
            self.extension_registry.require_executable(
                definition.extensions,
                self.profile.max_extension_state_bytes,
            )
        self.definitions_by_id = {definition.id: definition for definition in definitions}
        self.definitions_by_hash = {definition.definition_hash: definition for definition in definitions}
        for definition in definitions:
            for transition in definition.transitions:
                if transition.target_kind in {"ACTION", "CHILD_ACTION"}:
                    if transition.target_action not in self.definitions_by_id:
                        raise PCAMError(
                            ResultCode.DEFINITION_REJECTED,
                            PCAMFault.MISSING_REFERENCE,
                            str(transition.target_action),
                        )
        self.definition_set_hash = canonical_hash(
            [
                {
                    "definition_hash": definition.definition_hash,
                    "definition_id": definition.id,
                    "effect_registry_hash": canonical_hash(self.effect_registry),
                    "extension_registry_hash": self.extension_registry.identity_hash,
                    "interaction_profile_hash": canonical_hash(self.interaction_rules),
                    "runtime_profile_hash": self.profile.profile_hash,
                }
                for definition in sorted(definitions, key=lambda item: item.id)
            ]
        )

    def initial_state(
        self,
        resource_banks: dict[str, dict[str, int]] | None = None,
        slot_capacities: dict[str, dict[str, int]] | None = None,
        rng_streams: dict[str, object] | None = None,
        entity_records: dict[str, dict[str, object]] | None = None,
        pending_events: tuple[dict[str, object], ...] = (),
        freeze_tokens: tuple[FreezeToken, ...] = (),
        next_freeze_token_id: int = 1,
    ) -> SimulationState:
        action_slots = {
            str(entity): {
                slot: {"capacity": capacity, "instance_ids": [], "usage": 0}
                for slot, capacity in slots.items()
            }
            for entity, slots in (slot_capacities or {}).items()
        }
        return SimulationState(
            tick=0,
            definition_set_hash=self.definition_set_hash,
            entity_records=entity_records or {},
            resource_banks=resource_banks or {},
            action_slots=action_slots,
            pending_events=pending_events,
            freeze_tokens=freeze_tokens,
            next_freeze_token_id=next_freeze_token_id,
            rng_streams=rng_streams or {},
        )

    def tick(
        self,
        state: SimulationState,
        inputs: tuple[TickInput, ...] = (),
        host: HostSnapshot | None = None,
    ) -> tuple[SimulationState, dict[str, object]]:
        try:
            return self._tick_once(state, inputs, host)
        except PCAMError as error:
            contained = self._contain_fault(state, error)
            if contained is None:
                raise
            return contained

    def _tick_once(
        self,
        state: SimulationState,
        inputs: tuple[TickInput, ...] = (),
        host: HostSnapshot | None = None,
    ) -> tuple[SimulationState, dict[str, object]]:
        if state.definition_set_hash != self.definition_set_hash:
            raise PCAMError(
                ResultCode.SNAPSHOT_DEFINITION_MISMATCH,
                PCAMFault.SNAPSHOT_DEFINITION_MISMATCH,
                state.definition_set_hash,
            )
        if len(canonical_dumps(inputs)) > self.profile.max_snapshot_size_bytes:
            raise PCAMError(
                ResultCode.RUNTIME_FAULT,
                PCAMFault.STATE_INVARIANT_FAILURE,
                "tick input batch exceeds the bounded authoritative payload budget",
            )
        self._validate_limits(state, 0, 0)
        host = host or HostSnapshot()
        trace = self._empty_trace(state)
        work = state
        tick_buffers_before = self._buffer_trace_state(state)
        effects: list[Effect] = []
        typed_effects: list[EffectEnvelope] = []
        canonical_contacts = self._canonical_contacts(host.contacts)

        self._stage(trace, 1, "tick_start_snapshot")
        work, delivered_events = self._deliver_events(work)
        work = self.extension_registry.apply_tick_start(work, self.profile.extensions)
        for key in sorted(work.action_instances, key=int):
            action = work.action_instances[key]
            if action.lifecycle_state in {"TERMINATED", "FAULTED"}:
                continue
            definition = self.definitions_by_hash[action.definition_hash]
            try:
                work = self.extension_registry.apply_tick_start(work, definition.extensions)
            except PCAMError as error:
                raise error.with_context(
                    action_instance_id=action.instance_id,
                    owner_entity_id=action.owner_entity_id,
                ) from error
        trace["events_delivered"] = delivered_events
        work = replace(
            work,
            host_state={
                "contacts": [contact.__dict__ for contact in canonical_contacts],
                "imports": deepcopy(host.imports),
            },
        )

        self._stage(trace, 2, "input_ingestion")
        start_inputs = self._eligible_inputs(work.tick, inputs)
        buffers_before = self._buffer_trace_state(work)
        work = self._capture_inputs(work, start_inputs)
        buffers_after = self._buffer_trace_state(work)
        trace["buffer_changes"] = [
            {"after": list(buffers_after[key]), "before": list(buffers_before.get(key, ())), "instance_id": int(key)}
            for key in sorted(buffers_after, key=int)
            if buffers_after[key] != buffers_before.get(key, ())
        ]
        trace["input_order"] = [item.input_id for item in start_inputs]

        self._stage(trace, 3, "pre_advance_intent_evaluation")
        pre_intents, pre_eligible = self._evaluate_transitions(work, "PRE_ADVANCE")
        trace["eligible_transitions"].extend(pre_eligible)  # type: ignore[union-attr]

        self._stage(trace, 4, "pre_advance_arbitration")
        work, emitted, emitted_typed, pre_decisions = self._arbitrate_stage(work, pre_intents, start_inputs)
        effects.extend(emitted)
        typed_effects.extend(emitted_typed)
        trace["pre_advance_intents"] = pre_decisions
        self._extend_arbitration_trace(trace, pre_decisions)

        self._stage(trace, 5, "action_progression")
        for key in sorted(work.action_instances, key=lambda item: int(item)):
            action = work.action_instances[key]
            if action.lifecycle_state != "RUNNING":
                continue
            definition = self.definitions_by_hash[action.definition_hash]
            try:
                work, emitted, emitted_typed, quanta, node_changes = self._progress_action(
                    work,
                    action,
                    definition,
                    trace,
                )
            except PCAMError as error:
                raise error.with_context(
                    action_instance_id=action.instance_id,
                    owner_entity_id=action.owner_entity_id,
                ) from error
            effects.extend(emitted)
            typed_effects.extend(emitted_typed)
            trace.setdefault("progression_quanta", {})[key] = quanta  # type: ignore[index]
            if node_changes:
                trace.setdefault("node_changes", []).extend(node_changes)  # type: ignore[union-attr]

        self._stage(trace, 6, "post_advance_intent_evaluation_and_arbitration")
        post_intents, post_eligible = self._evaluate_transitions(work, "POST_ADVANCE")
        trace["eligible_transitions"].extend(post_eligible)  # type: ignore[union-attr]
        work, emitted, emitted_typed, post_decisions = self._arbitrate_stage(work, post_intents, [])
        effects.extend(emitted)
        typed_effects.extend(emitted_typed)
        trace["post_advance_intents"] = post_decisions
        self._extend_arbitration_trace(trace, post_decisions)

        self._stage(trace, 7, "semantic_snapshot")
        work, predicate_changes, facts, active_bindings = self._semantic_snapshot(work)
        trace["predicate_changes"] = predicate_changes
        trace["active_semantic_facts"] = facts

        self._stage(trace, 8, "contact_and_candidate_generation")
        candidates = list(canonical_contacts)
        trace["contact_candidates"] = [
            {
                "candidate_id": candidate.candidate_id,
                "contact_id": candidate.contact_id,
                "contact_partition": candidate.contact_partition,
                "defense_fact_id": candidate.defense_fact_id,
                "offense_fact_id": candidate.fact_id,
                "source_action_instance_id": candidate.source_instance_id,
                "source_entity_id": candidate.source_entity_id,
                "target_entity_id": candidate.target_entity_id,
            }
            for candidate in candidates
        ]
        trace["candidate_order"] = [candidate.candidate_id for candidate in candidates]

        self._stage(trace, 9, "interaction_resolution")
        work, interaction_effects, resolved_typed_effects, receipts = self._resolve_interactions(
            work,
            candidates,
            active_bindings,
        )
        effects.extend(interaction_effects)
        typed_effects.extend(resolved_typed_effects)
        trace["decision_record_mutations"] = receipts
        trace["interaction_rules_fired"] = [
            {"candidate_id": receipt["candidate_id"], **rule}
            for receipt in receipts
            for rule in receipt.get("rules_fired", [])
        ]
        trace["provisional_receipts"] = [
            {"candidate_id": receipt["candidate_id"], "receipt_written": True}
            for receipt in receipts
            if receipt.get("receipt_written") is True
        ]

        self._stage(trace, 10, "effect_reduction_and_commit")
        work, reduction_trace = self._commit_effects(work, effects, typed_effects)
        trace["effects_emitted"] = [effect.__dict__ for effect in effects]
        trace["typed_effects_emitted"] = [effect.__dict__ for effect in typed_effects]
        trace["effect_reduction"] = reduction_trace

        self._stage(trace, 11, "maintenance")
        work = self._maintenance(work)
        self._validate_limits(work, len(candidates), len(effects) + len(typed_effects))

        self._stage(trace, 12, "snapshot_and_digest")
        work = replace(work, tick=work.tick + 1)
        tick_buffers_after = self._buffer_trace_state(work)
        trace["buffer_changes"] = [
            {
                "after": list(tick_buffers_after.get(key, ())),
                "before": list(tick_buffers_before.get(key, ())),
                "instance_id": int(key),
            }
            for key in sorted(set(tick_buffers_before).union(tick_buffers_after), key=int)
            if tick_buffers_before.get(key, ()) != tick_buffers_after.get(key, ())
        ]
        digest = work.state_hash()
        trace["state_digest"] = digest
        trace["state_changes"] = work.to_snapshot()
        return work, trace

    def tick_with_fault_trace(
        self,
        state: SimulationState,
        inputs: tuple[TickInput, ...] = (),
        host: HostSnapshot | None = None,
    ) -> tuple[SimulationState, dict[str, object], PCAMError | None]:
        """Return a canonical fault trace while preserving the pre-tick state on failure."""

        try:
            next_state, trace = self.tick(state, inputs, host)
            return next_state, trace, None
        except PCAMError as error:
            trace = self._empty_trace(state)
            trace["faults"] = [
                {
                    "code": error.code.value,
                    "fault": error.fault.value,
                    "message": error.message,
                }
            ]
            trace["state_changes"] = state.to_snapshot()
            trace["state_digest"] = state.state_hash()
            return state, trace, error

    def _contain_fault(
        self,
        state: SimulationState,
        error: PCAMError,
    ) -> tuple[SimulationState, dict[str, object]] | None:
        policy = self.profile.fault_policy
        action = (
            state.action_instances.get(str(error.action_instance_id))
            if error.action_instance_id is not None
            else None
        )
        owner_entity_id = error.owner_entity_id
        if owner_entity_id is None and action is not None:
            owner_entity_id = action.owner_entity_id
        if policy == "ABORT_SIMULATION":
            return None
        if policy == "FAULT_ACTION" and action is None:
            return None
        if policy == "FAULT_ENTITY" and owner_entity_id is None:
            return None

        record: dict[str, object] = {
            "action_instance_id": action.instance_id if action is not None else None,
            "code": error.code.value,
            "contained": True,
            "fault": error.fault.value,
            "message": error.message,
            "owner_entity_id": owner_entity_id,
            "policy": policy,
            "tick": state.tick,
        }
        work = state
        if policy == "FAULT_ACTION":
            assert action is not None
            work, faulted = self._terminate_action(
                work,
                action,
                "FAULTED",
                error.fault.value,
            )
            work = _put_action(work, faulted)
        else:
            assert owner_entity_id is not None
            faulted_ids = {
                item.instance_id
                for item in work.action_instances.values()
                if item.owner_entity_id == owner_entity_id
                and item.lifecycle_state not in {"TERMINATED", "FAULTED"}
            }
            actions = {}
            for key, item in work.action_instances.items():
                if item.instance_id in faulted_ids:
                    item = replace(
                        item,
                        child_instance_ids=tuple(
                            child_id for child_id in item.child_instance_ids if child_id in faulted_ids
                        ),
                        lifecycle_state="FAULTED",
                        fault_record=error.fault.value,
                        parent_instance_id=(
                            item.parent_instance_id
                            if item.parent_instance_id in faulted_ids
                            else None
                        ),
                        parent_slot_id=(
                            item.parent_slot_id
                            if item.parent_instance_id in faulted_ids
                            else None
                        ),
                    )
                else:
                    item = replace(
                        item,
                        parent_instance_id=(
                            None if item.parent_instance_id in faulted_ids else item.parent_instance_id
                        ),
                        parent_slot_id=(
                            None if item.parent_instance_id in faulted_ids else item.parent_slot_id
                        ),
                        child_instance_ids=tuple(
                            child_id for child_id in item.child_instance_ids if child_id not in faulted_ids
                        ),
                    )
                actions[key] = item
            records = {key: dict(value) for key, value in work.entity_records.items()}
            entity_record = records.setdefault(str(owner_entity_id), {})
            entity_record["fault_record"] = record
            work = replace(
                work,
                action_instances=actions,
                entity_records=records,
                freeze_tokens=tuple(
                    token for token in work.freeze_tokens if token.target_id not in faulted_ids
                ),
            )

        fault_state = dict(work.fault_state)
        fault_state["last_fault"] = record
        work = self._rebuild_action_slots(replace(work, fault_state=fault_state))
        work = replace(work, tick=apply_u64(state.tick + 1))
        trace = self._empty_trace(state)
        trace["faults"] = [record]
        trace["stages"] = [{"index": 0, "name": "fault_containment"}]
        trace["state_changes"] = work.to_snapshot()
        trace["state_digest"] = work.state_hash()
        return work, trace

    @staticmethod
    def _empty_trace(state: SimulationState) -> dict[str, object]:
        return {
            "active_semantic_facts": [],
            "buffer_changes": [],
            "candidate_order": [],
            "claim_failures": [],
            "contact_candidates": [],
            "decision_record_mutations": [],
            "effect_reduction": [],
            "effects_emitted": [],
            "eligible_transitions": [],
            "faults": [],
            "input_order": [],
            "interaction_rules_fired": [],
            "node_changes": [],
            "predicate_changes": [],
            "progression_quanta": {},
            "provisional_receipts": [],
            "rejected_intents": [],
            "resource_reservations": [],
            "selected_transitions": [],
            "stages": [],
            "state_changes": {},
            "state_digest": state.state_hash(),
            "tick": state.tick,
            "typed_effects_emitted": [],
        }

    @staticmethod
    def _buffer_trace_state(state: SimulationState) -> dict[str, tuple[str, ...]]:
        return {
            key: tuple(entry.input_id for entry in action.input_buffer)
            for key, action in state.action_instances.items()
        }

    @staticmethod
    def _extend_arbitration_trace(trace: dict[str, object], decisions: list[dict[str, object]]) -> None:
        for decision in decisions:
            if decision["accepted"] and decision["intent_kind"] == "TRANSITION":
                trace["selected_transitions"].append(  # type: ignore[union-attr]
                    {
                        "intent_id": decision["intent_id"],
                        "transition_id": decision["transition_id"],
                    }
                )
            if not decision["accepted"]:
                rejected = {
                    "intent_id": decision["intent_id"],
                    "reason": decision["reason"],
                    "transition_id": decision["transition_id"],
                }
                trace["rejected_intents"].append(rejected)  # type: ignore[union-attr]
                if decision["claims"]:
                    trace["claim_failures"].append(rejected)  # type: ignore[union-attr]
            if decision["accepted"]:
                for claim in decision["claims"]:
                    if claim["kind"] == "RESOURCE":
                        trace["resource_reservations"].append(  # type: ignore[union-attr]
                            {
                                "amount": claim["amount"],
                                "intent_id": decision["intent_id"],
                                "owner_entity_id": decision["owner_entity_id"],
                                "resource": claim["key"],
                            }
                        )

    @staticmethod
    def _canonical_contacts(contacts: tuple[Contact, ...]) -> tuple[Contact, ...]:
        return tuple(sorted(
            contacts,
            key=lambda item: (
                item.source_entity_id,
                item.target_entity_id,
                item.source_instance_id,
                item.fact_id.encode("utf-8"),
                (item.defense_fact_id or "").encode("utf-8"),
                item.contact_partition.encode("utf-8"),
                item.contact_id.encode("utf-8"),
                item.candidate_id.encode("utf-8"),
            ),
        ))

    def save(self, state: SimulationState) -> dict[str, object]:
        self._validate_limits(state, 0, 0)
        return state.to_snapshot()

    def restore(self, snapshot: dict[str, object]) -> SimulationState:
        if len(canonical_dumps(snapshot)) > self.profile.max_snapshot_size_bytes:
            raise PCAMError(
                ResultCode.RUNTIME_FAULT,
                PCAMFault.STATE_INVARIANT_FAILURE,
                "snapshot exceeds max_snapshot_size_bytes",
            )
        state = SimulationState.from_snapshot(snapshot)
        if state.definition_set_hash != self.definition_set_hash:
            raise PCAMError(
                ResultCode.SNAPSHOT_DEFINITION_MISMATCH,
                PCAMFault.SNAPSHOT_DEFINITION_MISMATCH,
                state.definition_set_hash,
            )
        self._validate_limits(state, 0, 0)
        return state

    def _deliver_events(self, state: SimulationState) -> tuple[SimulationState, list[str]]:
        events = tuple(event_from_snapshot(dict(item)) for item in state.pending_events)
        frozen_targets = frozenset(
            event.target_id
            for event in events
            if event.delivery_mode in {"TARGET_ACTION", "PARENT", "CHILD"}
            and is_frozen(state.freeze_tokens, state.tick, event.target_id, "EVENT_DELIVERY")
        )
        delivered, pending = deliver_due(events, state.tick, frozen_targets)
        work = replace(state, pending_events=tuple(event_snapshot(item) for item in pending))
        for event in delivered:
            if event.delivery_mode in {"TARGET_ACTION", "PARENT", "CHILD"}:
                action = work.action_instances.get(str(event.target_id))
                if action is None:
                    raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, event.event_id)
                work = _put_action(work, replace(action, event_inbox=(*action.event_inbox, event_snapshot(event))))
            elif event.delivery_mode == "TARGET_ENTITY":
                records = {key: dict(value) for key, value in work.entity_records.items()}
                record = records.setdefault(str(event.target_id), {})
                record["event_inbox"] = [*record.get("event_inbox", []), event_snapshot(event)]
                work = replace(work, entity_records=records)
            elif event.delivery_mode == "BROADCAST":
                records = {key: dict(value) for key, value in work.entity_records.items()}
                for record in records.values():
                    record["event_inbox"] = [*record.get("event_inbox", []), event_snapshot(event)]
                work = replace(work, entity_records=records)
        return work, [item.event_id for item in delivered]

    def _eligible_inputs(self, tick: int, inputs: tuple[TickInput, ...]) -> list[TickInput]:
        dedup: dict[str, TickInput] = {}
        for item in inputs:
            if item.assigned_tick == tick and item.input_id not in dedup:
                dedup[item.input_id] = item
        return sorted(
            dedup.values(),
            key=lambda item: (
                item.source_entity_id,
                item.sequence,
                item.command_id.encode("utf-8"),
                item.input_id.encode("utf-8"),
            ),
        )

    def _arbitrate_stage(
        self,
        state: SimulationState,
        transitions: list[tuple[int, TransitionDefinition]],
        start_inputs: list[TickInput],
    ) -> tuple[SimulationState, list[Effect], list[EffectEnvelope], list[dict[str, object]]]:
        intents: list[Intent] = []
        for instance_id, transition in transitions:
            action = state.action_instances[str(instance_id)]
            matched = select_entry(action.input_buffer, transition.input_command) if transition.input_command else None
            claims = list(transition.claims)
            releases = []
            if transition.target_kind in {"ACTION", "CHILD_ACTION"}:
                assert transition.target_action is not None
                target_definition = self.definitions_by_id[transition.target_action]
                claims.extend(target_definition.start_claims)
                claims.extend(target_definition.slot_claims)
                claims.append(Claim("CAPACITY", "ACTIONS"))
                if transition.target_kind == "CHILD_ACTION":
                    assert transition.child_slot_id is not None
                    claims.append(
                        Claim(
                            "CHILD_SLOT",
                            transition.child_slot_id,
                            owner_id=action.instance_id,
                        )
                    )
                if transition.target_kind == "ACTION" and transition.source_disposition == "TERMINATE_SOURCE":
                    releases.append(Claim("CAPACITY", "ACTIONS"))
                    releases.extend(
                        Claim(
                            kind=str(raw["kind"]),  # type: ignore[arg-type]
                            key=str(raw["key"]),
                            amount=int(raw["amount"]),
                        )
                        for raw in action.slot_claims
                    )
            intents.append(
                Intent(
                    intent_kind="TRANSITION",
                    intent_priority=transition.priority,
                    owner_entity_id=action.owner_entity_id,
                    source_action_instance_id=instance_id,
                    transition_id=transition.id,
                    input_sequence=matched.sequence if matched else 0,
                    input_id=matched.input_id if matched else f"internal:{state.tick}:{instance_id}:{transition.id}",
                    claims=tuple(claims),
                    releases=tuple(releases),
                    operations=(
                        {
                            "instance_id": instance_id,
                            "kind": "TRANSITION",
                            "transition_id": transition.id,
                        },
                    ),
                )
            )
        for tick_input in start_inputs:
            if tick_input.action_definition_id is None:
                continue
            definition = self.definitions_by_id.get(tick_input.action_definition_id)
            if definition is None:
                raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, tick_input.action_definition_id)
            intents.append(
                Intent(
                    intent_kind="ACTION_START",
                    intent_priority=0,
                    owner_entity_id=tick_input.source_entity_id,
                    source_action_instance_id=0,
                    transition_id=definition.id,
                    input_sequence=tick_input.sequence,
                    input_id=tick_input.input_id,
                    claims=(
                        *definition.start_claims,
                        *definition.slot_claims,
                        Claim("CAPACITY", "ACTIONS"),
                    ),
                    operations=(
                        {
                            "definition_id": definition.id,
                            "kind": "START",
                            "owner_entity_id": tick_input.source_entity_id,
                            "parameters": tick_input.payload.get("parameters", {}),
                        },
                    ),
                )
            )
        arbitration_state = self._arbitration_state(state)
        capacities = dict(arbitration_state.capacities)
        usages = dict(arbitration_state.usages)
        for intent in intents:
            key = ("CAPACITY", intent.owner_entity_id, "ACTIONS")
            capacities[key] = self.profile.max_actions_per_entity
            usages[key] = sum(
                1
                for action in state.action_instances.values()
                if action.owner_entity_id == intent.owner_entity_id
                and action.lifecycle_state not in {"TERMINATED", "FAULTED"}
            )
        arbitration_state = replace(arbitration_state, capacities=capacities, usages=usages)
        reserved, decisions = arbitrate(tuple(intents), arbitration_state)
        state = replace(
            state,
            resource_banks={str(owner): dict(bank) for owner, bank in reserved.resource_banks.items()},
        )
        effects: list[Effect] = []
        typed_effects: list[EffectEnvelope] = []
        decision_trace: list[dict[str, object]] = []
        for decision in decisions:
            decision_trace.append(
                {
                    "accepted": decision.accepted,
                    "claims": [claim.__dict__ for claim in decision.intent.claims],
                    "intent_id": decision.intent.identity,
                    "intent_kind": decision.intent.intent_kind,
                    "owner_entity_id": decision.intent.owner_entity_id,
                    "reason": decision.reason,
                    "transition_id": decision.intent.transition_id,
                }
            )
            if not decision.accepted:
                state = self._consume_rejected_attempt(state, decision)
                continue
            for operation in decision.intent.operations:
                try:
                    if operation["kind"] == "START":
                        state, emitted_typed = self._start_action(
                            state,
                            str(operation["definition_id"]),
                            int(operation["owner_entity_id"]),
                            operation.get("parameters"),
                        )
                        typed_effects.extend(emitted_typed)
                    elif operation["kind"] == "TRANSITION":
                        instance_id = int(operation["instance_id"])
                        action = state.action_instances[str(instance_id)]
                        definition = self.definitions_by_hash[action.definition_hash]
                        transition = next(
                            item for item in definition.transitions if item.id == operation["transition_id"]
                        )
                        state, emitted, emitted_typed = self._apply_transition(
                            state,
                            instance_id,
                            transition,
                        )
                        effects.extend(emitted)
                        typed_effects.extend(emitted_typed)
                except PCAMError as error:
                    if operation["kind"] == "TRANSITION":
                        raise error.with_context(
                            action_instance_id=instance_id,
                            owner_entity_id=action.owner_entity_id,
                        ) from error
                    raise error.with_context(
                        owner_entity_id=int(operation["owner_entity_id"]),
                    ) from error
        return self._rebuild_action_slots(state), effects, typed_effects, decision_trace

    def _arbitration_state(self, state: SimulationState) -> ArbitrationState:
        capacities: dict[tuple[str, int, str], int] = {}
        usages: dict[tuple[str, int, str], int] = {}
        for entity, slots in state.action_slots.items():
            for slot, record in dict(slots).items():
                values = dict(record)
                key = ("ACTION_SLOT", int(entity), str(slot))
                capacities[key] = int(values["capacity"])
                usages[key] = int(values.get("usage", len(values.get("instance_ids", []))))
        for key in sorted(state.action_instances, key=int):
            action = state.action_instances[key]
            if action.lifecycle_state in {"TERMINATED", "FAULTED"}:
                continue
            definition = self.definitions_by_hash[action.definition_hash]
            for slot, capacity in definition.child_slot_capacities.items():
                claim_key = ("CHILD_SLOT", action.instance_id, slot)
                capacities[claim_key] = min(capacity, self.profile.max_children_per_action)
                usages[claim_key] = sum(
                    1
                    for child_id in action.child_instance_ids
                    if state.action_instances[str(child_id)].parent_slot_id == slot
                    and state.action_instances[str(child_id)].lifecycle_state not in {"TERMINATED", "FAULTED"}
                )
        return ArbitrationState(
            resource_banks={int(owner): dict(bank) for owner, bank in state.resource_banks.items()},
            capacities=capacities,
            usages=usages,
        )

    def _consume_rejected_attempt(self, state: SimulationState, decision: IntentDecision) -> SimulationState:
        if decision.intent.intent_kind != "TRANSITION":
            return state
        action = state.action_instances.get(str(decision.intent.source_action_instance_id))
        if action is None:
            return state
        definition = self.definitions_by_hash[action.definition_hash]
        transition = next(item for item in definition.transitions if item.id == decision.intent.transition_id)
        matched = select_entry(action.input_buffer, transition.input_command) if transition.input_command else None
        return _put_action(
            state,
            replace(
                action,
                input_buffer=apply_consumption(
                    action.input_buffer,
                    matched,
                    transition.consume_policy,
                    accepted=False,
                    attempted=True,
                ),
            ),
        )

    def _start_action(
        self,
        state: SimulationState,
        definition_id: str,
        owner_entity_id: int,
        supplied_parameters: object = None,
        parent_instance_id: int | None = None,
        parent_slot_id: str | None = None,
    ) -> tuple[SimulationState, list[EffectEnvelope]]:
        definition = self.definitions_by_id[definition_id]
        initial_node_id = definition.initial_node_id or definition.nodes[0].id
        node = next(item for item in definition.nodes if item.id == initial_node_id)
        if parent_instance_id is not None:
            depth = 1
            cursor = state.action_instances[str(parent_instance_id)]
            while cursor.parent_instance_id is not None:
                depth += 1
                cursor = state.action_instances[str(cursor.parent_instance_id)]
            if depth >= self.profile.max_action_nesting_depth:
                raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.NESTING_LIMIT_EXCEEDED, definition_id)
        instance_id = state.next_action_instance_id
        captured_parameters = self._capture_parameters(definition, supplied_parameters)
        action = ActionInstance(
            instance_id=instance_id,
            owner_entity_id=owner_entity_id,
            definition_hash=definition.definition_hash,
            lifecycle_state="RUNNING",
            current_node_id=node.id,
            current_rate_units=definition.units_per_tick,
            captured_parameters=captured_parameters,
            registers=dict(definition.register_initials),
            parent_instance_id=parent_instance_id,
            parent_slot_id=parent_slot_id,
            slot_claims=tuple(
                {
                    "amount": claim.amount,
                    "key": claim.key,
                    "kind": claim.kind,
                }
                for claim in definition.slot_claims
            ),
        )
        actions = dict(state.action_instances)
        actions[str(instance_id)] = action
        state = replace(state, action_instances=actions, next_action_instance_id=instance_id + 1)
        action = self._apply_assignments(state, action, definition, node.entry_assignments)
        action, effects = self._materialize_definition_effects(state, action, definition, node.entry_effects)
        if node.mode == "TERMINAL":
            state, action = self._terminate_action(state, action, "TERMINATED")
        return _put_action(state, action), effects

    def _rebuild_action_slots(self, state: SimulationState) -> SimulationState:
        rebuilt = {
            entity: {
                slot: {
                    "capacity": int(dict(record)["capacity"]),
                    "instance_ids": [],
                    "usage": 0,
                }
                for slot, record in dict(slots).items()
            }
            for entity, slots in state.action_slots.items()
        }
        for key in sorted(state.action_instances, key=int):
            action = state.action_instances[key]
            if action.lifecycle_state in {"TERMINATED", "FAULTED"}:
                continue
            entity = str(action.owner_entity_id)
            for raw_claim in action.slot_claims:
                claim = dict(raw_claim)
                if claim["kind"] != "ACTION_SLOT":
                    continue
                slot = str(claim["key"])
                if entity not in rebuilt or slot not in rebuilt[entity]:
                    raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, f"{entity}:{slot}")
                rebuilt[entity][slot]["instance_ids"].append(action.instance_id)
                rebuilt[entity][slot]["usage"] += int(claim["amount"])
        return replace(state, action_slots=rebuilt)

    def _capture_inputs(self, state: SimulationState, inputs: list[TickInput]) -> SimulationState:
        for key in sorted(state.action_instances, key=int):
            action = state.action_instances[key]
            if action.lifecycle_state not in {"RUNNING", "SUSPENDED"}:
                continue
            if is_frozen(state.freeze_tokens, state.tick, action.instance_id, "INPUT_CAPTURE"):
                continue
            definition = self.definitions_by_hash[action.definition_hash]
            entries = action.input_buffer
            for tick_input in inputs:
                if tick_input.source_entity_id != action.owner_entity_id:
                    continue
                entry = BufferEntry.capture(tick_input, lifetime=definition.default_buffer_lifetime)
                try:
                    entries = capture_entry(
                        entries,
                        entry,
                        capacity=definition.buffer_capacity,
                        overflow_policy=definition.buffer_overflow_policy,
                    )
                except PCAMError as error:
                    raise error.with_context(
                        action_instance_id=action.instance_id,
                        owner_entity_id=action.owner_entity_id,
                    ) from error
            state = _put_action(state, replace(action, input_buffer=entries))
        return state

    def _progress_action(
        self,
        state: SimulationState,
        action: ActionInstance,
        definition: ActionDefinition,
        trace: dict[str, object],
    ) -> tuple[SimulationState, list[Effect], list[EffectEnvelope], int, list[dict[str, object]]]:
        freeze_policy = progression_accrual(state.freeze_tokens, state.tick, action.instance_id)
        if freeze_policy == "HOLD":
            return state, [], [], 0, []
        accumulator = apply_u64(action.quantum_accumulator + action.current_rate_units)
        generated_quanta = accumulator // definition.rate_scale
        accumulator = accumulator % definition.rate_scale
        if freeze_policy == "ACCRUE":
            deferred = apply_u64(action.deferred_quanta + generated_quanta)
            frozen = replace(action, quantum_accumulator=accumulator, deferred_quanta=deferred)
            return _put_action(state, frozen), [], [], 0, []
        quanta = apply_u64(generated_quanta + action.deferred_quanta)
        if quanta > self.profile.max_quanta_per_action_per_tick:
            raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.QUANTUM_LIMIT_EXCEEDED, str(action.instance_id))
        effects: list[Effect] = []
        typed_effects: list[EffectEnvelope] = []
        changes: list[dict[str, object]] = []
        current = replace(action, quantum_accumulator=accumulator, deferred_quanta=0)
        transition_count = 0
        for _ in range(quanta):
            if current.lifecycle_state != "RUNNING":
                break
            current = replace(current, local_step=current.local_step + 1, node_step=current.node_step + 1)
            state = _put_action(state, current)
            eligible = self._eligible_transitions(state, current, definition, "AFTER_QUANTUM")
            trace["eligible_transitions"].extend(  # type: ignore[union-attr]
                {
                    "evaluation_point": "AFTER_QUANTUM",
                    "instance_id": action.instance_id,
                    "priority": transition.priority,
                    "transition_id": transition.id,
                }
                for transition in eligible
            )
            transition = eligible[0] if eligible else None
            if transition:
                transition_count += 1
                if transition_count > self.profile.max_internal_transitions_per_action_per_tick:
                    raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.TRANSITION_LIMIT_EXCEEDED, str(action.instance_id))
                before = current.current_node_id
                state, emitted, emitted_typed = self._apply_transition(state, action.instance_id, transition)
                effects.extend(emitted)
                typed_effects.extend(emitted_typed)
                trace["selected_transitions"].append(  # type: ignore[union-attr]
                    {
                        "instance_id": action.instance_id,
                        "transition_id": transition.id,
                    }
                )
                current = state.action_instances[str(action.instance_id)]
                changes.append({"instance_id": action.instance_id, "from": before, "to": current.current_node_id})
        return _put_action(state, current), effects, typed_effects, quanta, changes

    def _evaluate_transitions(
        self,
        state: SimulationState,
        point: str,
    ) -> tuple[list[tuple[int, TransitionDefinition]], list[dict[str, object]]]:
        selected: list[tuple[int, TransitionDefinition]] = []
        eligible_trace: list[dict[str, object]] = []
        for key in sorted(state.action_instances, key=lambda item: int(item)):
            action = state.action_instances[key]
            if action.lifecycle_state == "RUNNING":
                domain = "PRE_ADVANCE_TRANSITIONS" if point == "PRE_ADVANCE" else "POST_ADVANCE_TRANSITIONS"
                if is_frozen(state.freeze_tokens, state.tick, action.instance_id, domain):
                    continue
                definition = self.definitions_by_hash[action.definition_hash]
                try:
                    eligible = self._eligible_transitions(state, action, definition, point)
                except PCAMError as error:
                    raise error.with_context(
                        action_instance_id=action.instance_id,
                        owner_entity_id=action.owner_entity_id,
                    ) from error
                eligible_trace.extend(
                    {
                        "evaluation_point": point,
                        "instance_id": action.instance_id,
                        "priority": transition.priority,
                        "transition_id": transition.id,
                    }
                    for transition in eligible
                )
                transition = eligible[0] if eligible else None
                if transition:
                    selected.append((action.instance_id, transition))
        return sorted(selected, key=lambda item: item[0]), eligible_trace

    def _select_transition(
        self,
        state: SimulationState,
        action: ActionInstance,
        definition: ActionDefinition,
        point: str,
    ) -> TransitionDefinition | None:
        eligible = self._eligible_transitions(state, action, definition, point)
        return eligible[0] if eligible else None

    def _eligible_transitions(
        self,
        state: SimulationState,
        action: ActionInstance,
        definition: ActionDefinition,
        point: str,
    ) -> list[TransitionDefinition]:
        eligible = []
        for transition in definition.transitions:
            if transition.source_node != action.current_node_id or transition.evaluation_point != point:
                continue
            matched_input = select_entry(action.input_buffer, transition.input_command) if transition.input_command else None
            matched_event = next(
                (
                    event
                    for event in action.event_inbox
                    if event.get("event_type") == transition.event_type
                ),
                None,
            ) if transition.event_type else None
            if transition.input_command and matched_input is None:
                continue
            if transition.event_type and matched_event is None:
                continue
            if transition.guard_predicate and not action.predicate_truth_state.get(transition.guard_predicate, False):
                continue
            if transition.guard_expression is not None:
                guard = self._evaluate_action_expression(
                    state,
                    action,
                    definition,
                    transition.guard_expression,
                    self._transition_context(matched_input, matched_event),
                )
                if guard is not True:
                    continue
            eligible.append(transition)
        return sorted(eligible, key=lambda item: (-item.priority, item.id.encode("utf-8")))

    @staticmethod
    def _transition_context(
        matched_input: BufferEntry | None,
        matched_event: dict[str, object] | None,
    ) -> dict[str, object]:
        context: dict[str, object] = {}
        if matched_input is not None:
            context["input"] = deepcopy(matched_input.__dict__)
        if matched_event is not None:
            context["event"] = deepcopy(matched_event)
        return context

    def _apply_transition(
        self,
        state: SimulationState,
        instance_id: int,
        transition: TransitionDefinition,
    ) -> tuple[SimulationState, list[Effect], list[EffectEnvelope]]:
        action = state.action_instances.get(str(instance_id))
        if action is None or action.current_node_id != transition.source_node or action.lifecycle_state != "RUNNING":
            return state, [], []
        definition = self.definitions_by_hash[action.definition_hash]
        source_node = next(node for node in definition.nodes if node.id == action.current_node_id)
        matched_input = select_entry(action.input_buffer, transition.input_command) if transition.input_command else None
        matched_event = next(
            (
                event
                for event in action.event_inbox
                if event.get("event_type") == transition.event_type
            ),
            None,
        ) if transition.event_type else None
        context = self._transition_context(matched_input, matched_event)
        typed_effects: list[EffectEnvelope] = []

        action = self._apply_assignments(state, action, definition, source_node.exit_assignments, context)
        action = self._apply_assignments(state, action, definition, transition.exit_assignments, context)
        action, emitted = self._materialize_definition_effects(
            state,
            action,
            definition,
            source_node.exit_effects,
            context,
        )
        typed_effects.extend(emitted)
        action = self._apply_assignments(state, action, definition, transition.assignments, context)
        action = replace(action, cycle=apply_u64(action.cycle + transition.cycle_delta))
        action, emitted = self._materialize_definition_effects(
            state,
            action,
            definition,
            transition.definition_effects,
            context,
        )
        typed_effects.extend(emitted)
        action = self._apply_assignments(state, action, definition, transition.entry_assignments, context)
        state = _put_action(state, action)

        if transition.target_kind == "TERMINATE":
            state, action = self._terminate_action(state, action, "TERMINATED")
            action = replace(action, transition_serial=action.transition_serial + 1)
        elif transition.target_kind == "FAULT":
            assert transition.fault_code is not None
            state, action = self._terminate_action(state, action, "FAULTED", transition.fault_code)
            action = replace(action, transition_serial=action.transition_serial + 1)
        elif transition.target_kind == "ACTION":
            assert transition.target_action is not None
            owner_entity_id = action.owner_entity_id
            if transition.source_disposition == "TERMINATE_SOURCE":
                state, action = self._terminate_action(state, action, "TERMINATED")
                action = replace(action, transition_serial=action.transition_serial + 1)
            elif transition.source_disposition == "SUSPEND_SOURCE":
                action = replace(action, lifecycle_state="SUSPENDED", transition_serial=action.transition_serial + 1)
            else:
                action = replace(action, transition_serial=action.transition_serial + 1)
            action = replace(
                action,
                input_buffer=apply_consumption(
                    action.input_buffer,
                    matched_input,
                    transition.consume_policy,
                    accepted=True,
                    attempted=True,
                ),
            )
            state = _put_action(state, action)
            state, emitted = self._start_action(state, transition.target_action, owner_entity_id)
            typed_effects.extend(emitted)
            return state, list(transition.effects), typed_effects
        elif transition.target_kind == "CHILD_ACTION":
            assert transition.target_action is not None
            assert transition.child_slot_id is not None
            child_id = state.next_action_instance_id
            state, emitted = self._start_action(
                state,
                transition.target_action,
                action.owner_entity_id,
                parent_instance_id=action.instance_id,
                parent_slot_id=transition.child_slot_id,
            )
            typed_effects.extend(emitted)
            action = replace(
                action,
                transition_serial=action.transition_serial + 1,
                input_buffer=apply_consumption(
                    action.input_buffer,
                    matched_input,
                    transition.consume_policy,
                    accepted=True,
                    attempted=True,
                ),
            )
            if transition.parent_policy == "TERMINATE_PARENT":
                state, action = self._terminate_action(state, action, "TERMINATED")
                action = replace(action, child_instance_ids=(*action.child_instance_ids, child_id))
            else:
                action = replace(action, child_instance_ids=(*action.child_instance_ids, child_id))
                domains = {
                    "CONTINUE": (),
                    "FREEZE_PROGRESSION": ("PROGRESSION",),
                    "FREEZE_TRANSITIONS": ("PRE_ADVANCE_TRANSITIONS", "POST_ADVANCE_TRANSITIONS"),
                    "FREEZE_ALL_ACTION_LOGIC": (
                        "INPUT_CAPTURE",
                        "INTERACTION_EMISSION",
                        "INTERACTION_RECEPTION",
                        "POST_ADVANCE_TRANSITIONS",
                        "PRE_ADVANCE_TRANSITIONS",
                        "PROGRESSION",
                    ),
                }[str(transition.parent_policy)]
                if domains:
                    token_id = state.next_freeze_token_id
                    token = FreezeToken.created(
                        token_id=token_id,
                        source_id=child_id,
                        target_id=action.instance_id,
                        creation_tick=state.tick,
                        duration=U64_MAX,
                        domains=domains,  # type: ignore[arg-type]
                        metadata={"child_slot_id": transition.child_slot_id, "relationship": "PARENT_CHILD"},
                    )
                    state = replace(
                        state,
                        freeze_tokens=add_token(state.freeze_tokens, token),
                        next_freeze_token_id=apply_u64(token_id + 1),
                    )
                    action = replace(action, freeze_token_references=(*action.freeze_token_references, token_id))
            return _put_action(state, action), list(transition.effects), typed_effects
        else:
            assert transition.target_node is not None
            target_definition = next(node for node in definition.nodes if node.id == transition.target_node)
            action = replace(
                action,
                current_node_id=transition.target_node,
                node_step=transition.target_step,
                transition_serial=action.transition_serial + 1,
            )
            action = self._apply_assignments(
                state,
                action,
                definition,
                target_definition.entry_assignments,
                context,
            )
            action, emitted = self._materialize_definition_effects(
                state,
                action,
                definition,
                target_definition.entry_effects,
                context,
            )
            typed_effects.extend(emitted)
            if target_definition.mode == "TERMINAL":
                state, action = self._terminate_action(state, action, "TERMINATED")
        action = replace(
            action,
            input_buffer=apply_consumption(
                action.input_buffer,
                matched_input,
                transition.consume_policy,
                accepted=True,
                attempted=True,
            ),
        )
        return _put_action(state, action), list(transition.effects), typed_effects

    def _capture_parameters(
        self,
        definition: ActionDefinition,
        supplied_parameters: object,
    ) -> dict[str, object]:
        supplied = {} if supplied_parameters is None else supplied_parameters
        if not isinstance(supplied, dict) or any(type(key) is not str for key in supplied):
            raise PCAMError(
                ResultCode.INVALID_INPUT,
                PCAMFault.STATE_INVARIANT_FAILURE,
                f"{definition.id}: START parameters must be an object",
            )
        if not definition.parameter_declarations:
            if supplied:
                raise PCAMError(
                    ResultCode.INVALID_INPUT,
                    PCAMFault.MISSING_REFERENCE,
                    f"{definition.id}: action declares no parameters",
                )
            return deepcopy(definition.parameter_defaults)
        unknown = sorted(set(supplied) - set(definition.parameter_declarations))
        if unknown:
            raise PCAMError(
                ResultCode.INVALID_INPUT,
                PCAMFault.MISSING_REFERENCE,
                f"{definition.id}: unknown parameters: {unknown}",
            )
        captured: dict[str, object] = {}
        for parameter_id in sorted(
            definition.parameter_declarations,
            key=lambda item: item.encode("utf-8"),
        ):
            declaration = definition.parameter_declarations[parameter_id]
            if parameter_id in supplied:
                value = supplied[parameter_id]
            elif parameter_id in definition.parameter_defaults:
                value = definition.parameter_defaults[parameter_id]
            else:
                raise PCAMError(
                    ResultCode.INVALID_INPUT,
                    PCAMFault.MISSING_REFERENCE,
                    f"{definition.id}: missing required parameter: {parameter_id}",
                )
            normalized_declaration = {**declaration, "overflow": "FAULT"}
            try:
                normalized = self._normalize_register_value(
                    parameter_id,
                    value,
                    normalized_declaration,
                )
            except PCAMError as error:
                raise PCAMError(
                    ResultCode.INVALID_INPUT,
                    error.fault,
                    f"{definition.id}: invalid parameter {parameter_id}: {error.message}",
                ) from error
            allowed = declaration.get("allowed_values")
            if isinstance(allowed, list) and normalized not in allowed:
                raise PCAMError(
                    ResultCode.INVALID_INPUT,
                    PCAMFault.STATE_INVARIANT_FAILURE,
                    f"{definition.id}: parameter outside allowed_values: {parameter_id}",
                )
            captured[parameter_id] = deepcopy(normalized)
        return captured

    def _apply_assignments(
        self,
        state: SimulationState,
        action: ActionInstance,
        definition: ActionDefinition,
        assignments: tuple[Assignment, ...],
        context: dict[str, object] | None = None,
    ) -> ActionInstance:
        current = action
        for assignment in assignments:
            prefix = "action.register."
            if not assignment.target.startswith(prefix):
                raise PCAMError(
                    ResultCode.RUNTIME_FAULT,
                    PCAMFault.MISSING_REFERENCE,
                    assignment.target,
                )
            register_id = assignment.target.removeprefix(prefix)
            if register_id not in current.registers:
                raise PCAMError(
                    ResultCode.RUNTIME_FAULT,
                    PCAMFault.MISSING_REFERENCE,
                    assignment.target,
                )
            value = self._evaluate_action_expression(
                state,
                current,
                definition,
                assignment.value,
                context,
            )
            declaration = definition.register_declarations.get(register_id)
            normalized = self._normalize_register_value(register_id, value, declaration)
            registers = dict(current.registers)
            registers[register_id] = normalized
            current = replace(current, registers=registers)
        return current

    @staticmethod
    def _normalize_register_value(
        register_id: str,
        value: object,
        declaration: dict[str, object] | None,
    ) -> object:
        if declaration is None:
            return value
        kind = str(declaration["type"])
        if kind == "BOOL":
            if type(value) is bool:
                return value
        elif kind in {"I64", "U64"}:
            if type(value) is int:
                minimum = int(declaration["minimum"])
                maximum = int(declaration["maximum"])
                if minimum <= value <= maximum:
                    return value
                policy = str(declaration["overflow"])
                if policy == "SATURATE":
                    return min(max(value, minimum), maximum)
                if policy == "WRAP":
                    return minimum + ((value - minimum) % (maximum - minimum + 1))
                raise PCAMError(
                    ResultCode.RUNTIME_FAULT,
                    PCAMFault.INTEGER_OVERFLOW,
                    f"{register_id}: {value}",
                )
        elif kind in {"SYMBOL", "BYTES"}:
            if type(value) is str:
                return value
        elif kind in {"SET_SYMBOL", "FIXED_ARRAY", "BOUNDED_LIST"}:
            if isinstance(value, (list, tuple)):
                items = tuple(value)
                if kind != "SET_SYMBOL" or (
                    all(type(item) is str for item in items) and len(set(items)) == len(items)
                ):
                    capacity = int(declaration["capacity"])
                    if kind == "FIXED_ARRAY" and len(items) != capacity:
                        pass
                    elif len(items) <= capacity:
                        if kind == "SET_SYMBOL":
                            return tuple(sorted(items, key=lambda item: item.encode("utf-8")))
                        return items
                    elif str(declaration["overflow"]) == "SATURATE":
                        retained = items[:capacity]
                        if kind == "SET_SYMBOL":
                            return tuple(sorted(retained, key=lambda item: item.encode("utf-8")))
                        return retained
        raise PCAMError(
            ResultCode.RUNTIME_FAULT,
            PCAMFault.STATE_INVARIANT_FAILURE,
            f"invalid {kind} assignment for register {register_id}",
        )

    def _materialize_definition_effects(
        self,
        state: SimulationState,
        action: ActionInstance,
        definition: ActionDefinition,
        effects: tuple[DefinitionEffect, ...],
        context: dict[str, object] | None = None,
    ) -> tuple[ActionInstance, list[EffectEnvelope]]:
        current = action
        emitted: list[EffectEnvelope] = []
        for effect in effects:
            target = effect.target
            if target is None:
                target_entity_id = current.owner_entity_id
            elif type(target) is int:
                target_entity_id = apply_u64(target)
            elif isinstance(target, str):
                try:
                    resolved = self._resolve_action_reference(
                        state,
                        current,
                        definition,
                        target,
                        lambda _: False,
                    )
                except KeyError as exc:
                    raise PCAMError(
                        ResultCode.RUNTIME_FAULT,
                        PCAMFault.MISSING_REFERENCE,
                        target,
                    ) from exc
                if type(resolved) is not int:
                    raise PCAMError(
                        ResultCode.RUNTIME_FAULT,
                        PCAMFault.STATE_INVARIANT_FAILURE,
                        f"effect target is not an entity identifier: {target}",
                    )
                target_entity_id = apply_u64(resolved)
            else:  # pragma: no cover - schema validation prevents this path
                raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, effect.effect_type)
            effect_id = f"{state.tick}:{current.instance_id}:{current.emission_serial}"
            emitted.append(
                EffectEnvelope(
                    effect_id=effect_id,
                    effect_type=effect.effect_type,
                    effect_class=effect.effect_class or ("PRESENTATION" if not effect.authoritative else effect.effect_type),
                    source_entity_id=current.owner_entity_id,
                    target_entity_id=target_entity_id,
                    source_action_instance_id=current.instance_id,
                    origin_tick=state.tick,
                    priority=effect.priority,
                    payload=self._resolve_effect_payload(
                        state,
                        effect.payload,
                        current,
                        definition,
                        context,
                    ),
                    reducer=effect.reducer or "ORDERED",  # type: ignore[arg-type]
                    authoritative=effect.authoritative,
                )
            )
            current = replace(current, emission_serial=apply_u64(current.emission_serial + 1))
        return current, emitted

    def _terminate_action(
        self,
        state: SimulationState,
        action: ActionInstance,
        lifecycle: str,
        fault_record: str | None = None,
    ) -> tuple[SimulationState, ActionInstance]:
        definition = self.definitions_by_hash[action.definition_hash]
        work = state
        retained_children: list[int] = []
        for child_id in action.child_instance_ids:
            child = work.action_instances[str(child_id)]
            policy = definition.child_termination_policies[str(child.parent_slot_id)]
            if policy == "FAULT_IF_OCCUPIED":
                raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, str(action.instance_id))
            if policy == "TERMINATE_CHILD":
                work, child = self._terminate_action(work, child, "TERMINATED")
                work = _put_action(work, child)
                retained_children.append(child_id)
            elif policy == "DETACH_CHILD":
                work = _put_action(work, replace(child, parent_instance_id=None, parent_slot_id=None))
            else:
                retained_children.append(child_id)
        action = replace(
            action,
            child_instance_ids=tuple(retained_children),
            fault_record=fault_record,
            lifecycle_state=lifecycle,  # type: ignore[arg-type]
        )
        work = replace(
            work,
            freeze_tokens=tuple(token for token in work.freeze_tokens if token.target_id != action.instance_id),
        )
        return work, action

    def _semantic_snapshot(
        self,
        state: SimulationState,
    ) -> tuple[SimulationState, list[dict[str, object]], list[str], dict[tuple[int, str], FactBinding]]:
        changes: list[dict[str, object]] = []
        facts: list[str] = []
        active_bindings: dict[tuple[int, str], FactBinding] = {}
        for key in sorted(state.action_instances, key=lambda item: int(item)):
            action = state.action_instances[key]
            if action.lifecycle_state != "RUNNING":
                continue
            definition = self.definitions_by_hash[action.definition_hash]
            truth = dict(action.predicate_truth_state)
            entries = dict(action.predicate_entry_serials)
            exits = dict(action.predicate_exit_serials)
            try:
                current_values = self._predicate_values(state, action, definition)
            except PCAMError as error:
                raise error.with_context(
                    action_instance_id=action.instance_id,
                    owner_entity_id=action.owner_entity_id,
                ) from error
            for predicate in sorted(definition.predicates, key=lambda item: item.id.encode("utf-8")):
                now = current_values[predicate.id]
                before = truth.get(predicate.id, False)
                if now:
                    facts.append(f"{action.instance_id}:{predicate.id}")
                if now != before:
                    truth[predicate.id] = now
                    if predicate.track_edges:
                        serials = entries if now else exits
                        serials[predicate.id] = serials.get(predicate.id, 0) + 1
                    changes.append({"instance_id": action.instance_id, "predicate": predicate.id, "value": now})
            for binding in definition.semantic_facts:
                if truth.get(binding.when_predicate, False):
                    fact_key = (action.instance_id, binding.fact.fact_id)
                    active_bindings[fact_key] = binding
                    facts.append(f"{action.instance_id}:{binding.fact.fact_id}")
            state = _put_action(state, replace(action, predicate_truth_state=truth, predicate_entry_serials=entries, predicate_exit_serials=exits))
        return state, changes, sorted(set(facts)), active_bindings

    def _predicate_values(
        self,
        state: SimulationState | None,
        action: ActionInstance,
        definition: ActionDefinition,
        context: dict[str, object] | None = None,
    ) -> dict[str, bool]:
        definitions = {item.id: item for item in definition.predicates}
        values: dict[str, bool] = {}
        visiting: set[str] = set()

        def predicate_value(predicate_id: str) -> bool:
            if predicate_id in values:
                return values[predicate_id]
            if predicate_id in visiting or predicate_id not in definitions:
                raise PCAMError(
                    ResultCode.RUNTIME_FAULT,
                    PCAMFault.STATE_INVARIANT_FAILURE,
                    f"predicate dependency cycle or missing reference: {predicate_id}",
                )
            visiting.add(predicate_id)
            predicate = definitions[predicate_id]
            if predicate.expression is None:
                result = action.current_node_id in predicate.node_ids and action.node_step >= predicate.min_node_step
                if predicate.max_node_step_exclusive is not None:
                    result = result and action.node_step < predicate.max_node_step_exclusive
            else:
                result = evaluate(
                    predicate.expression,
                    lambda reference: self._resolve_action_reference(
                        state,
                        action,
                        definition,
                        reference,
                        predicate_value,
                        context,
                    ),
                    max_depth=self.profile.max_expression_depth,
                    max_nodes=self.profile.max_expression_nodes,
                )
                if type(result) is not bool:
                    raise PCAMError(
                        ResultCode.RUNTIME_FAULT,
                        PCAMFault.STATE_INVARIANT_FAILURE,
                        f"predicate did not evaluate to Boolean: {predicate_id}",
                    )
            visiting.remove(predicate_id)
            values[predicate_id] = result
            return result

        for predicate_id in sorted(definitions, key=lambda item: item.encode("utf-8")):
            predicate_value(predicate_id)
        return values

    def _evaluate_action_expression(
        self,
        state: SimulationState | None,
        action: ActionInstance,
        definition: ActionDefinition,
        expression: dict[str, object],
        context: dict[str, object] | None = None,
    ) -> object:
        predicates = self._predicate_values(state, action, definition, context)
        return evaluate(
            expression,
            lambda reference: self._resolve_action_reference(
                state,
                action,
                definition,
                reference,
                predicates.__getitem__,
                context,
            ),
            max_depth=self.profile.max_expression_depth,
            max_nodes=self.profile.max_expression_nodes,
        )

    @staticmethod
    def _resolve_action_reference(
        state: SimulationState | None,
        action: ActionInstance,
        definition: ActionDefinition,
        reference: str,
        predicate_value: object,
        context: dict[str, object] | None = None,
    ) -> object:
        fixed: dict[str, object] = {
            "action.cycle": action.cycle,
            "action.emission_serial": action.emission_serial,
            "action.instance_id": action.instance_id,
            "action.lifecycle": action.lifecycle_state,
            "action.local_step": action.local_step,
            "action.node": action.current_node_id,
            "action.node_step": action.node_step,
            "action.owner_entity_id": action.owner_entity_id,
            "action.transition_serial": action.transition_serial,
        }
        if reference in fixed:
            return fixed[reference]
        if reference.startswith("action.parameter."):
            return action.captured_parameters[reference.removeprefix("action.parameter.")]
        if reference.startswith("action.register."):
            return action.registers[reference.removeprefix("action.register.")]
        if reference.startswith("action.predicate."):
            name = reference.removeprefix("action.predicate.")
            return predicate_value(name)  # type: ignore[operator]
        if reference.startswith("owner.resource."):
            resource_id = reference.removeprefix("owner.resource.")
            if state is None:
                raise KeyError(reference)
            bank = state.resource_banks.get(str(action.owner_entity_id), {})
            if resource_id not in bank:
                raise KeyError(reference)
            return bank[resource_id]
        if reference.startswith("owner.register."):
            register_id = reference.removeprefix("owner.register.")
            if state is None:
                raise KeyError(reference)
            entity = state.entity_records.get(str(action.owner_entity_id), {})
            registers = entity.get("entity_registers", {})
            if not isinstance(registers, dict) or register_id not in registers:
                raise KeyError(reference)
            return registers[register_id]
        if reference.startswith("host."):
            import_id = reference.removeprefix("host.")
            declaration = definition.import_declarations.get(import_id)
            if declaration is None or state is None:
                raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.INVALID_HOST_IMPORT, import_id)
            imports = state.host_state.get("imports", {})
            if not isinstance(imports, dict):
                raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.INVALID_HOST_IMPORT, import_id)
            if import_id in imports:
                return TickExecutor._validate_host_import_value(
                    import_id,
                    imports[import_id],
                    declaration,
                )
            if declaration.get("failure_policy") == "USE_DEFAULT":
                return TickExecutor._validate_host_import_value(
                    import_id,
                    deepcopy(declaration["default"]),
                    declaration,
                )
            raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.INVALID_HOST_IMPORT, import_id)
        for prefix in ("input.", "event."):
            if reference.startswith(prefix):
                if context is None or prefix[:-1] not in context:
                    raise KeyError(reference)
                value: object = context[prefix[:-1]]
                for part in reference.removeprefix(prefix).split("."):
                    if not isinstance(value, dict) or part not in value:
                        raise KeyError(reference)
                    value = value[part]
                return value
        raise KeyError(reference)

    @staticmethod
    def _validate_host_import_value(
        import_id: str,
        value: object,
        declaration: dict[str, object],
    ) -> object:
        kind = str(declaration["type"])
        valid = (
            (kind == "BOOL" and type(value) is bool)
            or (kind == "I64" and type(value) is int and -(1 << 63) <= value <= (1 << 63) - 1)
            or (kind == "U64" and type(value) is int and 0 <= value <= (1 << 64) - 1)
            or (kind in {"SYMBOL", "BYTES"} and type(value) is str)
            or kind not in {"BOOL", "I64", "U64", "SYMBOL", "BYTES"}
        )
        if not valid:
            raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.INVALID_HOST_IMPORT, import_id)
        return deepcopy(value)

    def _bound_fact(
        self,
        state: SimulationState,
        fact: SemanticFact,
        action: ActionInstance,
        definition: ActionDefinition,
    ) -> SemanticFact:
        return replace(
            fact,
            effect_templates=tuple(
                replace(
                    template,
                    payload=self._resolve_effect_payload(state, template.payload, action, definition),
                )
                for template in fact.effect_templates
            ),
        )

    def _resolve_effect_payload(
        self,
        state: SimulationState,
        payload: object,
        action: ActionInstance,
        definition: ActionDefinition,
        context: dict[str, object] | None = None,
    ) -> object:
        if isinstance(payload, dict):
            if set(payload) in ({"literal"}, {"ref"}, {"op", "args"}):
                return self._evaluate_action_expression(
                    state,
                    action,
                    definition,
                    payload,
                    context,
                )
            if set(payload) == {"amount"}:
                return self._resolve_effect_payload(
                    state,
                    payload["amount"],
                    action,
                    definition,
                    context,
                )
            return {
                key: self._resolve_effect_payload(
                    state,
                    value,
                    action,
                    definition,
                    context,
                )
                for key, value in payload.items()
            }
        if isinstance(payload, list):
            return [
                self._resolve_effect_payload(
                    state,
                    value,
                    action,
                    definition,
                    context,
                )
                for value in payload
            ]
        return payload

    def _resolve_interactions(
        self,
        state: SimulationState,
        candidates: list[Contact],
        active_bindings: dict[tuple[int, str], FactBinding],
    ) -> tuple[SimulationState, list[Effect], list[EffectEnvelope], list[dict[str, object]]]:
        legacy_effects: list[Effect] = []
        typed_effects: list[EffectEnvelope] = []
        receipts: list[dict[str, object]] = []
        ledgers = {key: dict(value) for key, value in state.interaction_ledgers.items()}
        for candidate in candidates:
            action = state.action_instances.get(str(candidate.source_instance_id))
            if not action or action.lifecycle_state != "RUNNING":
                continue
            if is_frozen(state.freeze_tokens, state.tick, action.instance_id, "INTERACTION_EMISSION"):
                continue
            binding = active_bindings.get((candidate.source_instance_id, candidate.fact_id))
            if binding is None:
                if candidate.effect is None:
                    raise PCAMError(
                        ResultCode.RUNTIME_FAULT,
                        PCAMFault.INVALID_CONTACT,
                        candidate.candidate_id,
                        action.instance_id,
                        action.owner_entity_id,
                    )
                legacy_key = f"{candidate.source_instance_id}:{candidate.target_entity_id}:{candidate.fact_id}"
                if legacy_key in ledgers:
                    receipts.append({"candidate_id": candidate.candidate_id, "accepted": False, "reason": "ONCE_PER_ACTION_INSTANCE"})
                    continue
                ledgers[legacy_key] = {"origin_tick": state.tick, "candidate_id": candidate.candidate_id}
                legacy_effects.append(candidate.effect)
                receipts.append({"candidate_id": candidate.candidate_id, "accepted": True, "ledger_key": legacy_key})
                continue
            if binding.fact.direction != "OFFENSE":
                raise PCAMError(
                    ResultCode.RUNTIME_FAULT,
                    PCAMFault.INVALID_CONTACT,
                    candidate.candidate_id,
                    action.instance_id,
                    action.owner_entity_id,
                )
            context = LedgerContext(
                tick=state.tick,
                source_action_instance_id=action.instance_id,
                offense_fact_id=binding.fact.fact_id,
                target_entity_id=candidate.target_entity_id,
                cycle=action.cycle,
                predicate_entry_serials=action.predicate_entry_serials,
                contact_partition=candidate.contact_partition,
            )
            if not ledger_is_eligible(ledgers, binding.hit_policy, context):
                receipts.append({"candidate_id": candidate.candidate_id, "accepted": False, "reason": binding.hit_policy.kind})
                continue
            receipt_written = False
            if binding.hit_policy.receipt_on == "ON_CONTACT":
                ledgers, receipt = write_receipt(ledgers, binding.hit_policy, context, candidate.candidate_id)
                receipt_written = receipt is not None
            interaction_candidate = InteractionCandidate(
                tick=state.tick,
                candidate_id=candidate.candidate_id,
                source_entity_id=action.owner_entity_id,
                target_entity_id=candidate.target_entity_id,
                source_action_instance_id=action.instance_id,
                offense_fact_id=binding.fact.fact_id,
                contact_id=candidate.contact_id,
                contact_partition=candidate.contact_partition,
                host_context=candidate.host_context,
                defense_fact_id=candidate.defense_fact_id,
            )
            try:
                defenses = self._defense_map(state, active_bindings, candidate.defense_fact_id)
                definition = self.definitions_by_hash[action.definition_hash]
                offense = self._bound_fact(state, binding.fact, action, definition)
                decision = resolve_candidate(
                    interaction_candidate,
                    offense,
                    defenses,
                    self.interaction_rules,
                    max_redirects=self.profile.max_redirects_per_candidate,
                    max_expression_depth=self.profile.max_expression_depth,
                    max_expression_nodes=self.profile.max_expression_nodes,
                )
            except PCAMError as error:
                raise error.with_context(
                    action_instance_id=action.instance_id,
                    owner_entity_id=action.owner_entity_id,
                ) from error
            typed_effects.extend(decision.generated_effects)
            accepted = decision.status == "ACCEPTED"
            impact = any(item.authoritative for item in decision.generated_effects)
            if not receipt_written and receipt_required(binding.hit_policy.receipt_on, accepted, impact):
                ledgers, receipt = write_receipt(ledgers, binding.hit_policy, context, candidate.candidate_id)
                receipt_written = receipt is not None
            receipts.append(
                {
                    "accepted": accepted,
                    "candidate_id": candidate.candidate_id,
                    "decision_tags": list(decision.decision_tags),
                    "receipt_written": receipt_written,
                    "redirect_count": decision.redirect_count,
                    "rules_fired": list(decision.trace),
                }
            )
        return replace(state, interaction_ledgers=ledgers), legacy_effects, typed_effects, receipts

    def _defense_map(
        self,
        state: SimulationState,
        active_bindings: dict[tuple[int, str], FactBinding],
        required_fact_id: str | None,
    ) -> dict[int, SemanticFact | None]:
        by_target: dict[int, list[tuple[int, SemanticFact]]] = {}
        for (instance_id, _), binding in active_bindings.items():
            if binding.fact.direction != "DEFENSE":
                continue
            action = state.action_instances[str(instance_id)]
            if is_frozen(state.freeze_tokens, state.tick, action.instance_id, "INTERACTION_RECEPTION"):
                continue
            by_target.setdefault(action.owner_entity_id, []).append((instance_id, binding.fact))
        result: dict[int, SemanticFact | None] = {}
        for target, options in by_target.items():
            ordered = sorted(options, key=lambda item: (item[0], item[1].fact_id.encode("utf-8")))
            if required_fact_id is not None:
                ordered = [item for item in ordered if item[1].fact_id == required_fact_id]
            if len(ordered) > 1:
                raise PCAMError(
                    ResultCode.RUNTIME_FAULT,
                    PCAMFault.INVALID_CONTACT,
                    f"target {target} has ambiguous defense facts",
                )
            result[target] = ordered[0][1] if ordered else None
        return result

    def _commit_effects(
        self,
        state: SimulationState,
        effects: list[Effect],
        typed_effects: list[EffectEnvelope],
    ) -> tuple[SimulationState, list[dict[str, object]]]:
        banks = {entity: dict(values) for entity, values in state.resource_banks.items()}
        rng_streams = dict(state.rng_streams)
        pending_events = [event_from_snapshot(dict(item)) for item in state.pending_events]
        reduction_trace: list[dict[str, object]] = []
        for effect in sorted(
            effects,
            key=lambda item: (
                item.target_entity_id,
                item.kind.encode("utf-8"),
                -item.priority,
                item.source_entity_id,
                item.source_action_instance_id,
                item.id.encode("utf-8"),
            ),
        ):
            if effect.kind == "EVENT":
                assert effect.event_type is not None
                assert effect.delivery_mode is not None
                assert effect.payload is not None
                event = EventEnvelope.next_tick(
                    event_id=f"{state.tick}:{effect.source_action_instance_id}:{effect.id}",
                    event_type=effect.event_type,
                    source_id=effect.source_action_instance_id or effect.source_entity_id,
                    target_id=effect.target_entity_id,
                    origin_tick=state.tick,
                    payload=deepcopy(effect.payload),
                    delivery_mode=effect.delivery_mode,  # type: ignore[arg-type]
                )
                pending_events.append(event)
                try:
                    pending_events = list(canonical_events(tuple(pending_events)))
                except PCAMError as error:
                    raise PCAMError(
                        error.code,
                        error.fault,
                        error.message,
                        effect.source_action_instance_id,
                        effect.source_entity_id,
                    ) from error
                reduction_trace.append(
                    {
                        "delivery_tick": event.delivery_tick,
                        "effect_id": effect.id,
                        "effect_type": "pcam.event.create",
                        "event_id": event.event_id,
                    }
                )
                continue
            if effect.kind == "RNG_DRAW":
                snapshot = rng_streams.get(effect.resource)
                if not isinstance(snapshot, dict):
                    raise PCAMError(
                        ResultCode.RUNTIME_FAULT,
                        PCAMFault.RNG_PROFILE_MISMATCH,
                        effect.resource,
                        effect.source_action_instance_id,
                        effect.source_entity_id,
                    )
                try:
                    stream = PCG32Stream.from_snapshot(snapshot)
                    stream, value = stream.draw_u32()
                except (KeyError, TypeError, ValueError) as exc:
                    raise PCAMError(
                        ResultCode.RUNTIME_FAULT,
                        PCAMFault.RNG_PROFILE_MISMATCH,
                        effect.resource,
                        effect.source_action_instance_id,
                        effect.source_entity_id,
                    ) from exc
                rng_streams[effect.resource] = stream.to_snapshot()
                reduction_trace.append(
                    {
                        "draw_count": stream.draw_count,
                        "effect_id": effect.id,
                        "effect_type": "pcam.rng.draw",
                        "stream_id": effect.resource,
                        "value": value,
                    }
                )
                continue
            if effect.kind != "RESOURCE_DELTA":
                raise PCAMError(
                    ResultCode.RUNTIME_FAULT,
                    PCAMFault.UNKNOWN_EFFECT,
                    effect.kind,
                    effect.source_action_instance_id,
                    effect.source_entity_id,
                )
            entity = str(effect.target_entity_id)
            banks.setdefault(entity, {})
            banks[entity][effect.resource] = banks[entity].get(effect.resource, 0) + effect.amount
        authoritative = tuple(item for item in typed_effects if item.authoritative)
        try:
            reduced, rejected = reduce_effects(authoritative)
        except PCAMError as error:
            message = (
                "effect reduction integer overflow"
                if error.fault == PCAMFault.INTEGER_OVERFLOW
                else error.message
            )
            raise self._effect_fault_with_context(state, error, authoritative, message) from error
        for item in reduced:
            sources = tuple(
                effect
                for effect in authoritative
                if effect.effect_id in item.source_effect_ids
            )
            registration = self.effect_registry.get(item.effect_type)
            if registration is None or type(item.value) is not int:
                error = PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.UNKNOWN_EFFECT, item.effect_type)
                raise self._effect_fault_with_context(state, error, sources, error.message)
            resource, sign = registration
            entity = str(item.target_entity_id)
            banks.setdefault(entity, {})
            try:
                delta = mul_i64(item.value, sign)
                banks[entity][resource] = add_i64(banks[entity].get(resource, 0), delta)
            except PCAMError as error:
                raise self._effect_fault_with_context(
                    state,
                    error,
                    sources,
                    "effect commit integer overflow",
                ) from error
            reduction_trace.append(
                {
                    "effect_type": item.effect_type,
                    "reducer": item.reducer,
                    "source_effect_ids": list(item.source_effect_ids),
                    "target_entity_id": item.target_entity_id,
                    "value": item.value,
                }
            )
        reduction_trace.extend({"effect_id": item.effect_id, "reason": item.reason} for item in rejected)
        return replace(
            state,
            resource_banks=banks,
            rng_streams=rng_streams,
            pending_events=tuple(event_snapshot(item) for item in pending_events),
        ), reduction_trace

    @staticmethod
    def _effect_fault_with_context(
        state: SimulationState,
        error: PCAMError,
        effects: tuple[EffectEnvelope, ...],
        message: str,
    ) -> PCAMError:
        source_ids = {effect.source_action_instance_id for effect in effects}
        if len(source_ids) != 1:
            return PCAMError(error.code, error.fault, message)
        source_id = source_ids.pop()
        action = state.action_instances.get(str(source_id))
        if action is None:
            return PCAMError(error.code, error.fault, message)
        return PCAMError(
            error.code,
            error.fault,
            message,
            action_instance_id=source_id,
            owner_entity_id=action.owner_entity_id,
        )

    def _validate_limits(self, state: SimulationState, candidate_count: int, effect_count: int) -> None:
        if candidate_count > self.profile.max_candidates_per_tick or effect_count > self.profile.max_effects_per_tick:
            raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, str(state.tick))
        snapshot_size = len(canonical_dumps(state.to_snapshot()))
        if snapshot_size > self.profile.max_snapshot_size_bytes:
            raise PCAMError(
                ResultCode.RUNTIME_FAULT,
                PCAMFault.STATE_INVARIANT_FAILURE,
                "snapshot exceeds max_snapshot_size_bytes",
            )
        active_by_owner: dict[int, int] = {}
        event_counts: dict[int, int] = {}
        for raw_event in state.pending_events:
            target_id = int(raw_event["target_id"])
            event_counts[target_id] = event_counts.get(target_id, 0) + 1
        if any(count > self.profile.max_pending_events_per_entity for count in event_counts.values()):
            raise PCAMError(
                ResultCode.RUNTIME_FAULT,
                PCAMFault.STATE_INVARIANT_FAILURE,
                "pending event count exceeds runtime profile",
            )
        for action in state.action_instances.values():
            if len(action.input_buffer) > self.profile.max_buffer_entries_per_action:
                raise PCAMError(
                    ResultCode.RUNTIME_FAULT,
                    PCAMFault.STATE_INVARIANT_FAILURE,
                    f"input buffer exceeds runtime profile: {action.instance_id}",
                )
            active_children = sum(
                1
                for child_id in action.child_instance_ids
                if str(child_id) in state.action_instances
                and state.action_instances[str(child_id)].lifecycle_state not in {"TERMINATED", "FAULTED"}
            )
            if active_children > self.profile.max_children_per_action:
                raise PCAMError(
                    ResultCode.RUNTIME_FAULT,
                    PCAMFault.STATE_INVARIANT_FAILURE,
                    f"child count exceeds runtime profile: {action.instance_id}",
                )
            if action.lifecycle_state not in {"TERMINATED", "FAULTED"}:
                active_by_owner[action.owner_entity_id] = active_by_owner.get(action.owner_entity_id, 0) + 1
            depth = 0
            cursor = action
            visited: set[int] = set()
            while cursor.parent_instance_id is not None:
                if cursor.instance_id in visited or str(cursor.parent_instance_id) not in state.action_instances:
                    raise PCAMError(
                        ResultCode.RUNTIME_FAULT,
                        PCAMFault.STATE_INVARIANT_FAILURE,
                        f"invalid parent chain: {action.instance_id}",
                    )
                visited.add(cursor.instance_id)
                depth += 1
                cursor = state.action_instances[str(cursor.parent_instance_id)]
            if depth > self.profile.max_action_nesting_depth:
                raise PCAMError(
                    ResultCode.RUNTIME_FAULT,
                    PCAMFault.NESTING_LIMIT_EXCEEDED,
                    str(action.instance_id),
                )
        if any(count > self.profile.max_actions_per_entity for count in active_by_owner.values()):
            raise PCAMError(
                ResultCode.RUNTIME_FAULT,
                PCAMFault.STATE_INVARIANT_FAILURE,
                "action count exceeds runtime profile",
            )
        extension_state = {
            "actions": {
                key: action.extension_state
                for key, action in sorted(state.action_instances.items(), key=lambda item: int(item[0]))
                if action.extension_state
            },
            "simulation": state.extension_state,
        }
        has_extension_state = bool(state.extension_state) or bool(extension_state["actions"])
        if has_extension_state and len(canonical_dumps(extension_state)) > self.profile.max_extension_state_bytes:
            raise PCAMError(
                ResultCode.RUNTIME_FAULT,
                PCAMFault.EXTENSION_LIMIT_EXCEEDED,
                str(state.tick),
            )

    def _maintenance(self, state: SimulationState) -> SimulationState:
        state = self._finalize_child_results(state)
        for key in sorted(state.action_instances, key=int):
            action = state.action_instances[key]
            expiry_frozen = is_frozen(state.freeze_tokens, state.tick, action.instance_id, "BUFFER_EXPIRY")
            state = _put_action(
                state,
                replace(
                    action,
                    event_inbox=(),
                    input_buffer=expire_buffers(action.input_buffer, expiry_frozen),
                ),
            )
        records = {key: {**value, "event_inbox": []} for key, value in state.entity_records.items()}
        return replace(
            state,
            entity_records=records,
            freeze_tokens=expire_freezes(state.freeze_tokens, state.tick),
        )

    def _finalize_child_results(self, state: SimulationState) -> SimulationState:
        pending = [event_from_snapshot(dict(item)) for item in state.pending_events]
        work = state
        for key in sorted(state.action_instances, key=int):
            child = work.action_instances[key]
            if child.parent_instance_id is None or child.lifecycle_state not in {"TERMINATED", "FAULTED"}:
                continue
            if child.extension_state.get("pcam.child_result_emitted") is True:
                continue
            parent = work.action_instances.get(str(child.parent_instance_id))
            if parent is None:
                raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, str(child.instance_id))
            result_code = child.fault_record if child.lifecycle_state == "FAULTED" else "TERMINATED"
            event = EventEnvelope.next_tick(
                event_id=f"child-result:{child.instance_id}:{child.transition_serial}",
                event_type="CHILD_RESULT",
                source_id=child.instance_id,
                target_id=parent.instance_id,
                origin_tick=state.tick,
                payload={
                    "child_instance_id": child.instance_id,
                    "child_slot_id": child.parent_slot_id,
                    "parent_instance_id": parent.instance_id,
                    "result_code": result_code,
                    "termination_tick": state.tick,
                },
                delivery_mode="PARENT",
            )
            pending.append(event)
            work = _put_action(
                work,
                replace(
                    parent,
                    child_instance_ids=tuple(
                        instance_id for instance_id in parent.child_instance_ids if instance_id != child.instance_id
                    ),
                    freeze_token_references=tuple(
                        token_id
                        for token_id in parent.freeze_token_references
                        if any(
                            token.token_id == token_id
                            and not (
                                token.source_id == child.instance_id
                                and (token.metadata or {}).get("relationship") == "PARENT_CHILD"
                            )
                            for token in work.freeze_tokens
                        )
                    ),
                ),
            )
            extension_state = dict(child.extension_state)
            extension_state["pcam.child_result_emitted"] = True
            work = _put_action(work, replace(child, extension_state=extension_state))
            work = replace(
                work,
                freeze_tokens=tuple(
                    token
                    for token in work.freeze_tokens
                    if not (
                        token.source_id == child.instance_id
                        and token.target_id == parent.instance_id
                        and (token.metadata or {}).get("relationship") == "PARENT_CHILD"
                    )
                ),
            )
        return replace(work, pending_events=tuple(event_snapshot(item) for item in pending))

    @staticmethod
    def _stage(trace: dict[str, object], index: int, name: str) -> None:
        trace["stages"].append({"index": index, "name": name})  # type: ignore[index]


def _put_action(state: SimulationState, action: ActionInstance) -> SimulationState:
    actions = dict(state.action_instances)
    actions[str(action.instance_id)] = action
    return replace(state, action_instances=actions)
