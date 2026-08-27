"""Minimal 12-stage PCAM logical-tick executor."""

from __future__ import annotations

from dataclasses import replace

from .buffers import BufferEntry, apply_consumption, capture_entry, end_tick as expire_buffers, select_entry
from .canonical import canonical_hash
from .effects import EffectEnvelope, reduce_effects
from .errors import PCAMError, PCAMFault, ResultCode
from .freezes import end_tick as expire_freezes, is_frozen, progression_accrual
from .interactions import InteractionCandidate, InteractionRule, SemanticFact, resolve_candidate, validate_rules
from .ledgers import LedgerContext, is_eligible as ledger_is_eligible, receipt_required, write_receipt
from .model import ActionDefinition, Contact, Effect, FactBinding, HostSnapshot, RuntimeProfile, TickInput, TransitionDefinition, validate_definition
from .numeric import apply_u64
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

    def initial_state(self, resource_banks: dict[str, dict[str, int]] | None = None) -> SimulationState:
        return SimulationState(
            tick=0,
            definition_set_hash=self.definition_set_hash,
            resource_banks=resource_banks or {},
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
        work = replace(work, host_state={"contacts": [contact.__dict__ for contact in canonical_contacts], "imports": host.imports})

        self._stage(trace, 2, "input_ingestion")
        start_inputs = self._eligible_inputs(work.tick, inputs)
        work = self._capture_inputs(work, start_inputs)
        trace["input_order"] = [item.input_id for item in start_inputs]

        self._stage(trace, 3, "pre_advance_intent_evaluation")
        pre_intents = self._evaluate_transitions(work, "PRE_ADVANCE")

        self._stage(trace, 4, "pre_advance_arbitration")
        for instance_id, intent in pre_intents:
            work, emitted = self._apply_transition(work, instance_id, intent)
            effects.extend(emitted)
        for tick_input in start_inputs:
            if tick_input.action_definition_id:
                work = self._start_action(work, tick_input.action_definition_id, tick_input.source_entity_id)

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
        for instance_id, intent in self._evaluate_transitions(work, "POST_ADVANCE"):
            work, emitted = self._apply_transition(work, instance_id, intent)
            effects.extend(emitted)

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

    def _start_action(self, state: SimulationState, definition_id: str, owner_entity_id: int) -> SimulationState:
        definition = self.definitions_by_id[definition_id]
        node = definition.nodes[0]
        instance_id = state.next_action_instance_id
        action = ActionInstance(
            instance_id=instance_id,
            owner_entity_id=owner_entity_id,
            definition_hash=definition.definition_hash,
            current_node_id=node.id,
            current_rate_units=definition.units_per_tick,
        )
        actions = dict(state.action_instances)
        actions[str(instance_id)] = action
        return replace(state, action_instances=actions, next_action_instance_id=instance_id + 1)

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
            action = replace(action, lifecycle_state="TERMINATED", transition_serial=action.transition_serial + 1)
        elif transition.target_kind == "FAULT":
            action = replace(action, lifecycle_state="FAULTED", fault_record=transition.id, transition_serial=action.transition_serial + 1)
        else:
            assert transition.target_node is not None
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
        for key in sorted(state.action_instances, key=int):
            action = state.action_instances[key]
            expiry_frozen = is_frozen(state.freeze_tokens, state.tick, action.instance_id, "BUFFER_EXPIRY")
            state = _put_action(
                state,
                replace(action, input_buffer=expire_buffers(action.input_buffer, expiry_frozen)),
            )
        return replace(state, freeze_tokens=expire_freezes(state.freeze_tokens, state.tick))

    @staticmethod
    def _stage(trace: dict[str, object], index: int, name: str) -> None:
        trace["stages"].append({"index": index, "name": name})  # type: ignore[index]


def _put_action(state: SimulationState, action: ActionInstance) -> SimulationState:
    actions = dict(state.action_instances)
    actions[str(action.instance_id)] = action
    return replace(state, action_instances=actions)
