"""Bounded machine-readable runtime vector loading and execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .freezes import FreezeToken
from .interactions import EffectTemplate, InteractionRule, RuleOperation, SemanticFact
from .intents import Claim
from .ledgers import HitPolicy
from .model import (
    ActionDefinition,
    Contact,
    Effect,
    FactBinding,
    HostSnapshot,
    NetworkProfile,
    NodeDefinition,
    PredicateDefinition,
    RuntimeProfile,
    TickInput,
    TransitionDefinition,
)
from .rollback import RollbackManager
from .runtime import TickExecutor
from .state import SimulationState


@dataclass(frozen=True)
class VectorRun:
    executor: TickExecutor
    initial_snapshot: dict[str, object]
    final_state: SimulationState
    traces: tuple[dict[str, object], ...]
    input_history: dict[int, tuple[TickInput, ...]]
    host_history: dict[int, HostSnapshot]


def run_vector(document: dict[str, Any], max_ticks: int = 10_000) -> VectorRun:
    if document.get("kind") != "runtime_vector" or document.get("pcam_vector_version") != "1":
        raise ValueError("runtime vector requires kind=runtime_vector and pcam_vector_version=1")
    ticks = document.get("ticks", [])
    if not isinstance(ticks, list) or len(ticks) > max_ticks:
        raise ValueError("runtime vector tick count exceeds limit")
    definitions = tuple(_definition(item) for item in document.get("definitions", []))
    rules = tuple(_rule(item) for item in document.get("interaction_rules", []))
    profile_document = document.get("runtime_profile")
    if not isinstance(profile_document, dict):
        raise ValueError("runtime vector requires an explicit runtime_profile")
    profile = _runtime_profile(profile_document)
    registry = {
        str(effect_type): (str(value[0]), int(value[1]))
        for effect_type, value in document.get("effect_registry", {}).items()
    }
    executor = TickExecutor(definitions, profile, interaction_rules=rules, effect_registry=registry)
    initial = document.get("initial_state", {})
    state = executor.initial_state(
        resource_banks={str(key): dict(value) for key, value in initial.get("resource_banks", {}).items()},
        slot_capacities={str(key): dict(value) for key, value in initial.get("slot_capacities", {}).items()},
        rng_streams={str(key): dict(value) for key, value in initial.get("rng_streams", {}).items()},
        entity_records={str(key): dict(value) for key, value in initial.get("entity_records", {}).items()},
        pending_events=tuple(dict(value) for value in initial.get("pending_events", [])),
        freeze_tokens=tuple(_freeze_token(value) for value in initial.get("freeze_tokens", [])),
        next_freeze_token_id=int(initial.get("next_freeze_token_id", 1)),
    )
    initial_snapshot = executor.save(state)
    traces: list[dict[str, object]] = []
    input_history: dict[int, tuple[TickInput, ...]] = {}
    host_history: dict[int, HostSnapshot] = {}
    for expected_tick, tick in enumerate(ticks):
        if state.tick != expected_tick:
            raise ValueError("runtime vector ticks must begin at zero and be contiguous")
        inputs = tuple(_input(item) for item in tick.get("inputs", []))
        host = HostSnapshot(
            contacts=tuple(_contact(item) for item in tick.get("contacts", [])),
            imports=dict(tick.get("imports", {})),
        )
        input_history[state.tick] = inputs
        host_history[state.tick] = host
        state, trace = executor.tick(state, inputs, host)
        traces.append(trace)
    return VectorRun(executor, initial_snapshot, state, tuple(traces), input_history, host_history)


def rollback_vector(document: dict[str, Any]) -> tuple[SimulationState, SimulationState, tuple[dict[str, object], ...]]:
    direct = run_vector(document)
    rollback = document.get("rollback")
    if not isinstance(rollback, dict):
        raise ValueError("rollback-test requires a rollback object")
    corrected_tick = int(rollback["corrected_tick"])
    corrected_inputs = tuple(_input(item) for item in rollback["corrected_inputs"])
    predicted_history = dict(direct.input_history)
    predicted_history[corrected_tick] = tuple(
        _input(item) for item in rollback.get("predicted_inputs", [])
    )
    manager = RollbackManager(direct.executor)
    corrected, traces = manager.correct_and_resimulate(
        baseline_snapshot=direct.initial_snapshot,
        input_history=predicted_history,
        host_history=direct.host_history,
        corrected_tick=corrected_tick,
        corrected_inputs=corrected_inputs,
        until_tick=int(rollback.get("until_tick", len(document.get("ticks", [])))),
    )
    return direct.final_state, corrected, tuple(traces)


def _runtime_profile(value: dict[str, Any]) -> RuntimeProfile:
    limits = value["limits"]
    return RuntimeProfile(
        max_actions_per_entity=int(limits["max_actions_per_entity"]),
        max_action_nesting_depth=int(limits["max_action_nesting_depth"]),
        max_children_per_action=int(limits["max_children_per_action"]),
        max_quanta_per_action_per_tick=int(limits["max_quanta_per_action_per_tick"]),
        max_internal_transitions_per_action_per_tick=int(limits["max_internal_transitions_per_action_per_tick"]),
        max_buffer_entries_per_action=int(limits["max_buffer_entries_per_action"]),
        max_pending_events_per_entity=int(limits["max_pending_events_per_entity"]),
        max_candidates_per_tick=int(limits["max_candidates_per_tick"]),
        max_effects_per_tick=int(limits["max_effects_per_tick"]),
        max_redirects_per_candidate=int(limits["max_redirects_per_candidate"]),
        max_definition_size_bytes=int(limits["max_definition_size_bytes"]),
        max_snapshot_size_bytes=int(limits["max_snapshot_size_bytes"]),
        max_extension_state_bytes=int(limits["max_extension_state_bytes"]),
        max_expression_depth=int(limits.get("max_expression_depth", 64)),
        max_expression_nodes=int(limits.get("max_expression_nodes", 4096)),
        fault_policy=str(value["fault_policy"]),
        network_profiles=tuple(_network_profile(item) for item in value["network_profiles"]),
        id=str(value["id"]),
        revision=int(value["revision"]),
        rng_profiles=tuple(str(item) for item in value["rng_profiles"]),
        extensions=dict(value.get("extensions", {})),
    )


def _network_profile(value: dict[str, Any]) -> NetworkProfile:
    return NetworkProfile(
        id=str(value["id"]),
        topology=str(value["topology"]),  # type: ignore[arg-type]
        input_availability_policy=value.get("input_availability_policy"),
        predictor_id=value.get("predictor_id"),
        digest_interval_ticks=value.get("digest_interval_ticks"),
        desynchronization_policy=value.get("desynchronization_policy"),
        snapshot_interval_ticks=value.get("snapshot_interval_ticks"),
        retained_history_ticks=value.get("retained_history_ticks"),
        effect_reconciliation_policy=value.get("effect_reconciliation_policy"),
        correction_policy=value.get("correction_policy"),
        latency_mechanism=value.get("latency_mechanism"),
        max_latency_compensation_ticks=value.get("max_latency_compensation_ticks"),
    )


def _freeze_token(value: dict[str, Any]) -> FreezeToken:
    return FreezeToken(
        token_id=int(value["token_id"]),
        source_id=int(value["source_id"]),
        target_id=int(value["target_id"]),
        activation_tick=int(value["activation_tick"]),
        remaining_ticks=int(value["remaining_ticks"]),
        domains=tuple(value["domains"]),  # type: ignore[arg-type]
        accrual_policy=str(value.get("accrual_policy", "HOLD")),  # type: ignore[arg-type]
        stack_group=str(value.get("stack_group", "default")),
        stack_policy=str(value.get("stack_policy", "INDEPENDENT")),  # type: ignore[arg-type]
        metadata=value.get("metadata"),
    )


def _definition(value: dict[str, Any]) -> ActionDefinition:
    return ActionDefinition(
        id=str(value["id"]),
        rate_scale=int(value["rate_scale"]),
        units_per_tick=int(value["units_per_tick"]),
        nodes=tuple(
            NodeDefinition(
                id=str(item["id"]),
                mode=str(item.get("mode", "EVENT_DRIVEN")),  # type: ignore[arg-type]
                duration_quanta=item.get("duration_quanta"),
                seekable=bool(item.get("seekable", False)),
            )
            for item in value["nodes"]
        ),
        predicates=tuple(
            PredicateDefinition(
                id=str(item["id"]),
                node_ids=tuple(item.get("node_ids", ())),
                min_node_step=int(item.get("min_node_step", 0)),
                max_node_step_exclusive=item.get("max_node_step_exclusive"),
            )
            for item in value.get("predicates", [])
        ),
        semantic_facts=tuple(_fact_binding(item) for item in value.get("semantic_facts", [])),
        transitions=tuple(_transition(item) for item in value.get("transitions", [])),
        start_claims=tuple(_claim(item) for item in value.get("start_claims", [])),
        slot_claims=tuple(_claim(item) for item in value.get("slot_claims", [])),
        child_slot_capacities={str(key): int(item) for key, item in value.get("child_slot_capacities", {}).items()},
        child_termination_policies={str(key): str(item) for key, item in value.get("child_termination_policies", {}).items()},
        buffer_capacity=int(value.get("buffer_capacity", 8)),
        buffer_overflow_policy=str(value.get("buffer_overflow_policy", "DROP_OLDEST")),  # type: ignore[arg-type]
        default_buffer_lifetime=int(value.get("default_buffer_lifetime", 1)),
        metadata=dict(value.get("metadata", {})),
        extensions=dict(value.get("extensions", {})),
        parameter_defaults=dict(value.get("parameter_defaults", {})),
        register_initials={str(key): int(item) for key, item in value.get("register_initials", {}).items()},
        initial_node_id=value.get("initial_node_id"),
    )


def _fact_binding(value: dict[str, Any]) -> FactBinding:
    fact = value["fact"]
    policy = value["hit_policy"]
    return FactBinding(
        fact=SemanticFact(
            fact_id=str(fact["fact_id"]),
            direction=str(fact["direction"]),  # type: ignore[arg-type]
            channels=tuple(fact.get("channels", ())),
            tags=tuple(fact.get("tags", ())),
            attributes=dict(fact.get("attributes", {})),
            effect_templates=tuple(_effect_template(item) for item in fact.get("effect_templates", [])),
        ),
        when_predicate=str(value["when_predicate"]),
        hit_policy=HitPolicy(
            kind=str(policy["kind"]),  # type: ignore[arg-type]
            receipt_on=str(policy["receipt_on"]),  # type: ignore[arg-type]
            cooldown_ticks=policy.get("cooldown_ticks"),
            predicate_id=policy.get("predicate_id"),
        ),
    )


def _effect_template(value: dict[str, Any]) -> EffectTemplate:
    return EffectTemplate(
        effect_type=str(value["effect_type"]),
        effect_class=str(value["effect_class"]),
        payload=value["payload"],
        reducer=str(value.get("reducer", "ORDERED")),
        priority=int(value.get("priority", 0)),
        authoritative=bool(value.get("authoritative", True)),
    )


def _transition(value: dict[str, Any]) -> TransitionDefinition:
    return TransitionDefinition(
        id=str(value["id"]),
        source_node=str(value["source_node"]),
        evaluation_point=str(value["evaluation_point"]),  # type: ignore[arg-type]
        priority=int(value["priority"]),
        target_kind=str(value.get("target_kind", "NODE")),  # type: ignore[arg-type]
        target_node=value.get("target_node"),
        target_action=value.get("target_action"),
        target_step=int(value.get("target_step", 0)),
        source_disposition=str(value.get("source_disposition", "TERMINATE_SOURCE")),  # type: ignore[arg-type]
        child_slot_id=value.get("child_slot_id"),
        parent_policy=value.get("parent_policy"),
        guard_predicate=value.get("guard_predicate"),
        guard_expression=value.get("guard_expression"),
        input_command=value.get("input_command"),
        event_type=value.get("event_type"),
        consume_policy=str(value.get("consume_policy", "ON_ACCEPT")),  # type: ignore[arg-type]
        claims=tuple(_claim(item) for item in value.get("claims", [])),
        effects=tuple(_effect(item) for item in value.get("effects", [])),
        cycle_delta=int(value.get("cycle_delta", 0)),
    )


def _effect(value: dict[str, Any]) -> Effect:
    return Effect(
        id=str(value["id"]),
        kind=str(value.get("kind", "RESOURCE_DELTA")),  # type: ignore[arg-type]
        effect_class=str(value.get("effect_class", "RESOURCE")),
        source_entity_id=int(value.get("source_entity_id", 0)),
        target_entity_id=int(value.get("target_entity_id", 0)),
        source_action_instance_id=int(value.get("source_action_instance_id", 0)),
        origin_tick=int(value.get("origin_tick", 0)),
        resource=str(value.get("resource", "hp")),
        amount=int(value.get("amount", 0)),
        priority=int(value.get("priority", 0)),
    )


def _claim(value: dict[str, Any]) -> Claim:
    return Claim(
        kind=str(value["kind"]),  # type: ignore[arg-type]
        key=str(value["key"]),
        amount=int(value.get("amount", 1)),
        owner_id=value.get("owner_id"),
    )


def _rule(value: dict[str, Any]) -> InteractionRule:
    return InteractionRule(
        rule_id=str(value["rule_id"]),
        stage=str(value["stage"]),  # type: ignore[arg-type]
        order=int(value["order"]),
        condition=dict(value["condition"]),
        operations=tuple(_rule_operation(item) for item in value.get("operations", [])),
        stop_stage=bool(value.get("stop_stage", False)),
        stop_pipeline=bool(value.get("stop_pipeline", False)),
    )


def _rule_operation(value: dict[str, Any]) -> RuleOperation:
    data = dict(value.get("data", {}))
    for key in ("template", "replacement"):
        if key in data:
            data[key] = _effect_template(data[key])
    return RuleOperation(str(value["op"]), data)


def _input(value: dict[str, Any]) -> TickInput:
    return TickInput(
        input_id=str(value["input_id"]),
        source_entity_id=int(value["source_entity_id"]),
        sequence=int(value["sequence"]),
        command_id=str(value["command_id"]),
        assigned_tick=int(value["assigned_tick"]),
        payload=dict(value.get("payload", {})),
        action_definition_id=value.get("action_definition_id"),
    )


def _contact(value: dict[str, Any]) -> Contact:
    return Contact(
        candidate_id=str(value["candidate_id"]),
        source_instance_id=int(value["source_instance_id"]),
        target_entity_id=int(value["target_entity_id"]),
        fact_id=str(value["fact_id"]),
        source_entity_id=int(value["source_entity_id"]),
        contact_partition=str(value.get("contact_partition", "default")),
        contact_id=str(value["contact_id"]),
        host_context=dict(value.get("host_context", {})),
        defense_fact_id=value.get("defense_fact_id"),
    )
