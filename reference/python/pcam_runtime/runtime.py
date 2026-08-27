"""Minimal 12-stage PCAM logical-tick executor."""

from __future__ import annotations

from dataclasses import replace

from .canonical import canonical_hash
from .errors import PCAMError, PCAMFault, ResultCode
from .model import ActionDefinition, Contact, Effect, HostSnapshot, RuntimeProfile, TickInput, TransitionDefinition, validate_definition
from .state import ActionInstance, SimulationState


class TickExecutor:
    def __init__(self, definitions: tuple[ActionDefinition, ...], profile: RuntimeProfile | None = None):
        self.profile = profile or RuntimeProfile()
        for definition in definitions:
            validate_definition(definition)
        self.definitions_by_id = {definition.id: definition for definition in definitions}
        self.definitions_by_hash = {definition.definition_hash: definition for definition in definitions}
        self.definition_set_hash = canonical_hash(
            [
                {
                    "definition_hash": definition.definition_hash,
                    "definition_id": definition.id,
                    "effect_registry_hash": canonical_hash(["RESOURCE_DELTA", "EVENT"]),
                    "extension_registry_hash": canonical_hash([]),
                    "interaction_profile_hash": canonical_hash({"ledger": "ONCE_PER_ACTION_INSTANCE"}),
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

        self._stage(trace, 1, "tick_start_snapshot")
        work = replace(work, host_state={"contacts": [contact.__dict__ for contact in host.contacts], "imports": host.imports})

        self._stage(trace, 2, "input_ingestion")
        start_inputs = self._eligible_inputs(work.tick, inputs)
        trace["input_order"] = [item.input_id for item in start_inputs]

        self._stage(trace, 3, "pre_advance_intent_evaluation")
        pre_intents = self._evaluate_transitions(work, "PRE_ADVANCE", start_inputs)

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
        for instance_id, intent in self._evaluate_transitions(work, "POST_ADVANCE", start_inputs):
            work, emitted = self._apply_transition(work, instance_id, intent)
            effects.extend(emitted)

        self._stage(trace, 7, "semantic_snapshot")
        work, predicate_changes, facts = self._semantic_snapshot(work)
        trace["predicate_changes"] = predicate_changes
        trace["active_semantic_facts"] = facts

        self._stage(trace, 8, "contact_and_candidate_generation")
        candidates = sorted(
            host.contacts,
            key=lambda item: (
                item.source_entity_id,
                item.target_entity_id,
                item.source_instance_id,
                item.fact_id.encode("utf-8"),
                item.contact_partition.encode("utf-8"),
                item.contact_id.encode("utf-8"),
                item.candidate_id.encode("utf-8"),
            ),
        )
        trace["candidate_order"] = [candidate.candidate_id for candidate in candidates]

        self._stage(trace, 9, "interaction_resolution")
        work, interaction_effects, receipts = self._resolve_interactions(work, candidates)
        effects.extend(interaction_effects)
        trace["decision_record_mutations"] = receipts

        self._stage(trace, 10, "effect_reduction_and_commit")
        work = self._commit_effects(work, effects)
        trace["effects_emitted"] = [effect.__dict__ for effect in effects]

        self._stage(trace, 11, "maintenance")
        self._validate_limits(work, len(candidates), len(effects))

        self._stage(trace, 12, "snapshot_and_digest")
        work = replace(work, tick=work.tick + 1)
        digest = work.state_hash()
        trace["state_digest"] = digest
        trace["state_changes"] = work.to_snapshot()
        return work, trace

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

    def _progress_action(
        self,
        state: SimulationState,
        action: ActionInstance,
        definition: ActionDefinition,
    ) -> tuple[SimulationState, list[Effect], int, list[dict[str, object]]]:
        accumulator = action.quantum_accumulator + action.current_rate_units
        quanta = accumulator // definition.rate_scale
        accumulator = accumulator % definition.rate_scale
        if quanta > self.profile.max_quanta_per_action_per_tick:
            raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.QUANTUM_LIMIT_EXCEEDED, str(action.instance_id))
        effects: list[Effect] = []
        changes: list[dict[str, object]] = []
        current = replace(action, quantum_accumulator=accumulator)
        transition_count = 0
        for _ in range(quanta):
            if current.lifecycle_state != "RUNNING":
                break
            current = replace(current, local_step=current.local_step + 1, node_step=current.node_step + 1)
            state = _put_action(state, current)
            transition = self._select_transition(current, definition, "AFTER_QUANTUM", ())
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
        inputs: tuple[TickInput, ...] | list[TickInput],
    ) -> list[tuple[int, TransitionDefinition]]:
        selected: list[tuple[int, TransitionDefinition]] = []
        for key in sorted(state.action_instances, key=lambda item: int(item)):
            action = state.action_instances[key]
            if action.lifecycle_state == "RUNNING":
                definition = self.definitions_by_hash[action.definition_hash]
                transition = self._select_transition(action, definition, point, inputs)
                if transition:
                    selected.append((action.instance_id, transition))
        return sorted(selected, key=lambda item: item[0])

    def _select_transition(
        self,
        action: ActionInstance,
        definition: ActionDefinition,
        point: str,
        inputs: tuple[TickInput, ...] | list[TickInput],
    ) -> TransitionDefinition | None:
        eligible = []
        input_commands = {item.command_id for item in inputs}
        for transition in definition.transitions:
            if transition.source_node != action.current_node_id or transition.evaluation_point != point:
                continue
            if transition.input_command and transition.input_command not in input_commands:
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
        return _put_action(state, action), list(transition.effects)

    def _semantic_snapshot(self, state: SimulationState) -> tuple[SimulationState, list[dict[str, object]], list[str]]:
        changes: list[dict[str, object]] = []
        facts: list[str] = []
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
            state = _put_action(state, replace(action, predicate_truth_state=truth, predicate_entry_serials=entries, predicate_exit_serials=exits))
        return state, changes, sorted(facts)

    def _resolve_interactions(self, state: SimulationState, candidates: list[Contact]) -> tuple[SimulationState, list[Effect], list[dict[str, object]]]:
        effects: list[Effect] = []
        receipts: list[dict[str, object]] = []
        ledgers = {key: dict(value) for key, value in state.interaction_ledgers.items()}
        for candidate in candidates:
            action = state.action_instances.get(str(candidate.source_instance_id))
            if not action or action.lifecycle_state != "RUNNING":
                continue
            ledger_key = f"{candidate.source_instance_id}:{candidate.target_entity_id}:{candidate.fact_id}"
            if ledger_key in ledgers:
                receipts.append({"candidate_id": candidate.candidate_id, "accepted": False, "reason": "ONCE_PER_ACTION_INSTANCE"})
                continue
            ledgers[ledger_key] = {"origin_tick": state.tick, "candidate_id": candidate.candidate_id}
            effects.append(candidate.effect)
            receipts.append({"candidate_id": candidate.candidate_id, "accepted": True, "ledger_key": ledger_key})
        return replace(state, interaction_ledgers=ledgers), effects, receipts

    def _commit_effects(self, state: SimulationState, effects: list[Effect]) -> SimulationState:
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
        return replace(state, resource_banks=banks)

    def _validate_limits(self, state: SimulationState, candidate_count: int, effect_count: int) -> None:
        if candidate_count > self.profile.max_candidates_per_tick or effect_count > self.profile.max_effects_per_tick:
            raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, str(state.tick))

    @staticmethod
    def _stage(trace: dict[str, object], index: int, name: str) -> None:
        trace["stages"].append({"index": index, "name": name})  # type: ignore[index]


def _put_action(state: SimulationState, action: ActionInstance) -> SimulationState:
    actions = dict(state.action_instances)
    actions[str(action.instance_id)] = action
    return replace(state, action_instances=actions)
