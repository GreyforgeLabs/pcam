"""Minimal 12-stage PCAM logical-tick executor."""

from __future__ import annotations

from dataclasses import replace

from .buffers import BufferEntry, apply_consumption, capture_entry, end_tick as expire_buffers, select_entry
from .canonical import canonical_hash
from .effects import EffectEnvelope, reduce_effects
from .errors import PCAMError, PCAMFault, ResultCode
from .events import EventEnvelope, deliver_due, event_from_snapshot, event_snapshot
from .freezes import FreezeToken, add_token, end_tick as expire_freezes, is_frozen, progression_accrual
from .interactions import InteractionCandidate, InteractionRule, SemanticFact, resolve_candidate, validate_rules
from .intents import ArbitrationState, Claim, Intent, IntentDecision, arbitrate
from .ledgers import LedgerContext, is_eligible as ledger_is_eligible, receipt_required, write_receipt
from .model import ActionDefinition, Contact, Effect, FactBinding, HostSnapshot, RuntimeProfile, TickInput, TransitionDefinition, validate_definition
from .numeric import U64_MAX, apply_u64
from .state import ActionInstance, SimulationState


class TickExecutor:
    def __init__(
        self,
        definitions: tuple[ActionDefinition, ...],
        profile: RuntimeProfile | None = None,
        interaction_rules: tuple[InteractionRule, ...] = (),
        effect_registry: dict[str, tuple[str, int]] | None = None,
    ):
        self.profile = profile or RuntimeProfile()
        validate_rules(interaction_rules)
        self.interaction_rules = interaction_rules
        self.effect_registry = effect_registry or {
            "combat.damage": ("hp", -1),
            "combat.stagger": ("stagger", 1),
        }
        for definition in definitions:
            validate_definition(definition)
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
                    "extension_registry_hash": canonical_hash([]),
                    "interaction_profile_hash": canonical_hash(self.interaction_rules),
                    "runtime_profile_hash": canonical_hash(self.profile),
                }
                for definition in sorted(definitions, key=lambda item: item.id)
            ]
        )

    def initial_state(
        self,
        resource_banks: dict[str, dict[str, int]] | None = None,
        slot_capacities: dict[str, dict[str, int]] | None = None,
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
            resource_banks=resource_banks or {},
            action_slots=action_slots,
        )

    def tick(
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
        host = host or HostSnapshot()
        trace: dict[str, object] = {"tick": state.tick, "stages": []}
        work = state
        effects: list[Effect] = []
        typed_effects: list[EffectEnvelope] = []
        canonical_contacts = self._canonical_contacts(host.contacts)

        self._stage(trace, 1, "tick_start_snapshot")
        work, delivered_events = self._deliver_events(work)
        trace["events_delivered"] = delivered_events
        work = replace(work, host_state={"contacts": [contact.__dict__ for contact in canonical_contacts], "imports": host.imports})

        self._stage(trace, 2, "input_ingestion")
        start_inputs = self._eligible_inputs(work.tick, inputs)
        work = self._capture_inputs(work, start_inputs)
        trace["input_order"] = [item.input_id for item in start_inputs]

        self._stage(trace, 3, "pre_advance_intent_evaluation")
        pre_intents = self._evaluate_transitions(work, "PRE_ADVANCE")

        self._stage(trace, 4, "pre_advance_arbitration")
        work, emitted, pre_decisions = self._arbitrate_stage(work, pre_intents, start_inputs)
        effects.extend(emitted)
        trace["pre_advance_intents"] = pre_decisions

        self._stage(trace, 5, "action_progression")
        for key in sorted(work.action_instances, key=lambda item: int(item)):
            action = work.action_instances[key]
            if action.lifecycle_state != "RUNNING":
                continue
            definition = self.definitions_by_hash[action.definition_hash]
            work, emitted, quanta, node_changes = self._progress_action(work, action, definition)
            effects.extend(emitted)
            trace.setdefault("progression_quanta", {})[key] = quanta  # type: ignore[index]
            if node_changes:
                trace.setdefault("node_changes", []).extend(node_changes)  # type: ignore[union-attr]

        self._stage(trace, 6, "post_advance_intent_evaluation_and_arbitration")
        post_intents = self._evaluate_transitions(work, "POST_ADVANCE")
        work, emitted, post_decisions = self._arbitrate_stage(work, post_intents, [])
        effects.extend(emitted)
        trace["post_advance_intents"] = post_decisions

        self._stage(trace, 7, "semantic_snapshot")
        work, predicate_changes, facts, active_bindings = self._semantic_snapshot(work)
        trace["predicate_changes"] = predicate_changes
        trace["active_semantic_facts"] = facts

        self._stage(trace, 8, "contact_and_candidate_generation")
        candidates = list(canonical_contacts)
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
        digest = work.state_hash()
        trace["state_digest"] = digest
        trace["state_changes"] = work.to_snapshot()
        return work, trace

    @staticmethod
    def _canonical_contacts(contacts: tuple[Contact, ...]) -> tuple[Contact, ...]:
        return tuple(sorted(
            contacts,
            key=lambda item: (
                item.source_entity_id,
                item.target_entity_id,
                item.source_instance_id,
                item.fact_id.encode("utf-8"),
                item.contact_partition.encode("utf-8"),
                item.contact_id.encode("utf-8"),
                item.candidate_id.encode("utf-8"),
            ),
        ))

    def save(self, state: SimulationState) -> dict[str, object]:
        return state.to_snapshot()

    def restore(self, snapshot: dict[str, object]) -> SimulationState:
        state = SimulationState.from_snapshot(snapshot)
        if state.definition_set_hash != self.definition_set_hash:
            raise PCAMError(
                ResultCode.SNAPSHOT_DEFINITION_MISMATCH,
                PCAMFault.SNAPSHOT_DEFINITION_MISMATCH,
                state.definition_set_hash,
            )
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
    ) -> tuple[SimulationState, list[Effect], list[dict[str, object]]]:
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
        decision_trace: list[dict[str, object]] = []
        for decision in decisions:
            decision_trace.append(
                {
                    "accepted": decision.accepted,
                    "intent_id": decision.intent.identity,
                    "reason": decision.reason,
                }
            )
            if not decision.accepted:
                state = self._consume_rejected_attempt(state, decision)
                continue
            for operation in decision.intent.operations:
                if operation["kind"] == "START":
                    state = self._start_action(
                        state,
                        str(operation["definition_id"]),
                        int(operation["owner_entity_id"]),
                    )
                elif operation["kind"] == "TRANSITION":
                    instance_id = int(operation["instance_id"])
                    action = state.action_instances[str(instance_id)]
                    definition = self.definitions_by_hash[action.definition_hash]
                    transition = next(
                        item for item in definition.transitions if item.id == operation["transition_id"]
                    )
                    state, emitted = self._apply_transition(state, instance_id, transition)
                    effects.extend(emitted)
        return self._rebuild_action_slots(state), effects, decision_trace

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
        parent_instance_id: int | None = None,
        parent_slot_id: str | None = None,
    ) -> SimulationState:
        definition = self.definitions_by_id[definition_id]
        node = definition.nodes[0]
        if parent_instance_id is not None:
            depth = 1
            cursor = state.action_instances[str(parent_instance_id)]
            while cursor.parent_instance_id is not None:
                depth += 1
                cursor = state.action_instances[str(cursor.parent_instance_id)]
            if depth >= self.profile.max_action_nesting_depth:
                raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.NESTING_LIMIT_EXCEEDED, definition_id)
        instance_id = state.next_action_instance_id
        action = ActionInstance(
            instance_id=instance_id,
            owner_entity_id=owner_entity_id,
            definition_hash=definition.definition_hash,
            lifecycle_state="TERMINATED" if node.mode == "TERMINAL" else "RUNNING",
            current_node_id=node.id,
            current_rate_units=definition.units_per_tick,
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
        return replace(state, action_instances=actions, next_action_instance_id=instance_id + 1)

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
                entries = capture_entry(
                    entries,
                    entry,
                    capacity=definition.buffer_capacity,
                    overflow_policy=definition.buffer_overflow_policy,
                )
            state = _put_action(state, replace(action, input_buffer=entries))
        return state

    def _progress_action(
        self,
        state: SimulationState,
        action: ActionInstance,
        definition: ActionDefinition,
    ) -> tuple[SimulationState, list[Effect], int, list[dict[str, object]]]:
        freeze_policy = progression_accrual(state.freeze_tokens, state.tick, action.instance_id)
        if freeze_policy == "HOLD":
            return state, [], 0, []
        accumulator = apply_u64(action.quantum_accumulator + action.current_rate_units)
        generated_quanta = accumulator // definition.rate_scale
        accumulator = accumulator % definition.rate_scale
        if freeze_policy == "ACCRUE":
            deferred = apply_u64(action.deferred_quanta + generated_quanta)
            frozen = replace(action, quantum_accumulator=accumulator, deferred_quanta=deferred)
            return _put_action(state, frozen), [], 0, []
        quanta = apply_u64(generated_quanta + action.deferred_quanta)
        if quanta > self.profile.max_quanta_per_action_per_tick:
            raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.QUANTUM_LIMIT_EXCEEDED, str(action.instance_id))
        effects: list[Effect] = []
        changes: list[dict[str, object]] = []
        current = replace(action, quantum_accumulator=accumulator, deferred_quanta=0)
        transition_count = 0
        for _ in range(quanta):
            if current.lifecycle_state != "RUNNING":
                break
            current = replace(current, local_step=current.local_step + 1, node_step=current.node_step + 1)
            state = _put_action(state, current)
            transition = self._select_transition(current, definition, "AFTER_QUANTUM")
            if transition:
                transition_count += 1
                if transition_count > self.profile.max_internal_transitions_per_action_per_tick:
                    raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.TRANSITION_LIMIT_EXCEEDED, str(action.instance_id))
                before = current.current_node_id
                state, emitted = self._apply_transition(state, action.instance_id, transition)
                effects.extend(emitted)
                current = state.action_instances[str(action.instance_id)]
                changes.append({"instance_id": action.instance_id, "from": before, "to": current.current_node_id})
        return _put_action(state, current), effects, quanta, changes

    def _evaluate_transitions(
        self,
        state: SimulationState,
        point: str,
    ) -> list[tuple[int, TransitionDefinition]]:
        selected: list[tuple[int, TransitionDefinition]] = []
        for key in sorted(state.action_instances, key=lambda item: int(item)):
            action = state.action_instances[key]
            if action.lifecycle_state == "RUNNING":
                domain = "PRE_ADVANCE_TRANSITIONS" if point == "PRE_ADVANCE" else "POST_ADVANCE_TRANSITIONS"
                if is_frozen(state.freeze_tokens, state.tick, action.instance_id, domain):
                    continue
                definition = self.definitions_by_hash[action.definition_hash]
                transition = self._select_transition(action, definition, point)
                if transition:
                    selected.append((action.instance_id, transition))
        return sorted(selected, key=lambda item: item[0])

    def _select_transition(
        self,
        action: ActionInstance,
        definition: ActionDefinition,
        point: str,
    ) -> TransitionDefinition | None:
        eligible = []
        for transition in definition.transitions:
            if transition.source_node != action.current_node_id or transition.evaluation_point != point:
                continue
            if transition.input_command and select_entry(action.input_buffer, transition.input_command) is None:
                continue
            if transition.event_type and not any(
                event.get("event_type") == transition.event_type for event in action.event_inbox
            ):
                continue
            if transition.guard_predicate and not action.predicate_truth_state.get(transition.guard_predicate, False):
                continue
            eligible.append(transition)
        return max(eligible, key=lambda item: item.priority) if eligible else None

    def _apply_transition(
        self,
        state: SimulationState,
        instance_id: int,
        transition: TransitionDefinition,
    ) -> tuple[SimulationState, list[Effect]]:
        action = state.action_instances.get(str(instance_id))
        if action is None or action.current_node_id != transition.source_node or action.lifecycle_state != "RUNNING":
            return state, []
        matched_input = select_entry(action.input_buffer, transition.input_command) if transition.input_command else None
        if transition.target_kind == "TERMINATE":
            state, action = self._terminate_action(state, action, "TERMINATED")
            action = replace(action, transition_serial=action.transition_serial + 1)
        elif transition.target_kind == "FAULT":
            state, action = self._terminate_action(state, action, "FAULTED", transition.id)
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
            state = self._start_action(state, transition.target_action, owner_entity_id)
            return state, list(transition.effects)
        elif transition.target_kind == "CHILD_ACTION":
            assert transition.target_action is not None
            assert transition.child_slot_id is not None
            child_id = state.next_action_instance_id
            state = self._start_action(
                state,
                transition.target_action,
                action.owner_entity_id,
                parent_instance_id=action.instance_id,
                parent_slot_id=transition.child_slot_id,
            )
            action = replace(
                action,
                child_instance_ids=(*action.child_instance_ids, child_id),
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
                action = replace(action, lifecycle_state="TERMINATED")
            else:
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
            return _put_action(state, action), list(transition.effects)
        else:
            assert transition.target_node is not None
            definition = self.definitions_by_hash[action.definition_hash]
            target_definition = next(node for node in definition.nodes if node.id == transition.target_node)
            if target_definition.mode == "TERMINAL":
                state, action = self._terminate_action(state, action, "TERMINATED")
            action = replace(
                action,
                current_node_id=transition.target_node,
                node_step=transition.target_step,
                transition_serial=action.transition_serial + 1,
            )
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
        return _put_action(state, action), list(transition.effects)

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
            for predicate in definition.predicates:
                now = action.current_node_id in predicate.node_ids and action.node_step >= predicate.min_node_step
                if predicate.max_node_step_exclusive is not None:
                    now = now and action.node_step < predicate.max_node_step_exclusive
                before = truth.get(predicate.id, False)
                if now:
                    facts.append(f"{action.instance_id}:{predicate.id}")
                if now != before:
                    truth[predicate.id] = now
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
                    raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.INVALID_CONTACT, candidate.candidate_id)
                legacy_key = f"{candidate.source_instance_id}:{candidate.target_entity_id}:{candidate.fact_id}"
                if legacy_key in ledgers:
                    receipts.append({"candidate_id": candidate.candidate_id, "accepted": False, "reason": "ONCE_PER_ACTION_INSTANCE"})
                    continue
                ledgers[legacy_key] = {"origin_tick": state.tick, "candidate_id": candidate.candidate_id}
                legacy_effects.append(candidate.effect)
                receipts.append({"candidate_id": candidate.candidate_id, "accepted": True, "ledger_key": legacy_key})
                continue
            if binding.fact.direction != "OFFENSE":
                raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.INVALID_CONTACT, candidate.candidate_id)
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
            )
            defenses = self._defense_map(state, active_bindings, candidate.defense_fact_id)
            decision = resolve_candidate(
                interaction_candidate,
                binding.fact,
                defenses,
                self.interaction_rules,
                max_redirects=self.profile.max_redirects_per_candidate,
            )
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
            if effect.kind != "RESOURCE_DELTA":
                raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.UNKNOWN_EFFECT, effect.kind)
            entity = str(effect.target_entity_id)
            banks.setdefault(entity, {})
            banks[entity][effect.resource] = banks[entity].get(effect.resource, 0) + effect.amount
        authoritative = tuple(item for item in typed_effects if item.authoritative)
        reduced, rejected = reduce_effects(authoritative)
        reduction_trace: list[dict[str, object]] = []
        for item in reduced:
            registration = self.effect_registry.get(item.effect_type)
            if registration is None or type(item.value) is not int:
                raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.UNKNOWN_EFFECT, item.effect_type)
            resource, sign = registration
            entity = str(item.target_entity_id)
            banks.setdefault(entity, {})
            banks[entity][resource] = banks[entity].get(resource, 0) + item.value * sign
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
        return replace(state, resource_banks=banks), reduction_trace

    def _validate_limits(self, state: SimulationState, candidate_count: int, effect_count: int) -> None:
        if candidate_count > self.profile.max_candidates_per_tick or effect_count > self.profile.max_effects_per_tick:
            raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, str(state.tick))

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
