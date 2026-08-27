"""Compile validated schema documents into immutable runtime records."""

from __future__ import annotations

from typing import Any

from .errors import PCAMError, PCAMFault, ResultCode
from .interactions import EffectTemplate, InteractionRule, RuleOperation, SemanticFact
from .intents import Claim
from .ledgers import HitPolicy
from .model import ActionDefinition, FactBinding, NodeDefinition, PredicateDefinition, TransitionDefinition
from .schema import validate_document


def action_from_document(document: dict[str, Any]) -> ActionDefinition:
    _require_valid(document, "action")
    nodes = tuple(
        NodeDefinition(
            id=str(value["id"]),
            mode=str(value["mode"]),  # type: ignore[arg-type]
            duration_quanta=value.get("duration_quanta"),
            seekable=bool(value["seekable"]),
        )
        for _, value in sorted(document["nodes"].items(), key=lambda item: item[0].encode("utf-8"))
    )
    predicates = tuple(
        PredicateDefinition(
            id=str(predicate_id),
            expression=dict(value["expression"]),
            track_edges=bool(value["track_edges"]),
        )
        for predicate_id, value in sorted(
            document["predicates"].items(),
            key=lambda item: item[0].encode("utf-8"),
        )
    )
    parameters = {
        str(parameter_id): value["default"]
        for parameter_id, value in document["parameters"].items()
        if "default" in value
    }
    registers: dict[str, int] = {}
    for register_id, value in document["registers"].items():
        initial = value["initial"]
        if type(initial) is not int:
            raise PCAMError(
                ResultCode.DEFINITION_REJECTED,
                PCAMFault.STATE_INVARIANT_FAILURE,
                f"reference slice supports integer register initials only: {register_id}",
            )
        registers[str(register_id)] = initial
    limits = document["limits"]
    return ActionDefinition(
        id=str(document["id"]),
        rate_scale=int(document["rate"]["scale"]),
        units_per_tick=int(document["rate"]["units_per_tick"]),
        nodes=nodes,
        predicates=predicates,
        semantic_facts=tuple(_fact_binding(value) for value in document["semantic_facts"]),
        transitions=tuple(_transition(value) for value in document["transitions"]),
        slot_claims=tuple(_slot_claim(value) for value in document["slot_claims"]),
        buffer_capacity=int(limits["buffer_capacity"]),
        buffer_overflow_policy=str(limits["buffer_overflow_policy"]),  # type: ignore[arg-type]
        metadata=dict(document["metadata"]),
        extensions=dict(document["extensions"]),
        parameter_defaults=parameters,
        register_initials=registers,
        initial_node_id=str(document["initial_node"]),
    )


def interaction_rules_from_document(document: dict[str, Any]) -> tuple[InteractionRule, ...]:
    _require_valid(document, "interaction_profile")
    return tuple(
        InteractionRule(
            rule_id=str(value["id"]),
            stage=str(value["stage"]),  # type: ignore[arg-type]
            order=int(value["order"]),
            condition=dict(value["condition"]),
            operations=tuple(_operation(item) for item in value["operations"]),
            stop_stage=bool(value["stop_stage"]),
            stop_pipeline=bool(value["stop_pipeline"]),
        )
        for value in sorted(
            document["rules"],
            key=lambda item: (str(item["stage"]), int(item["order"]), str(item["id"]).encode("utf-8")),
        )
    )


def _fact_binding(value: dict[str, Any]) -> FactBinding:
    when = value["when"]
    reference = when.get("ref") if isinstance(when, dict) else None
    prefix = "action.predicate."
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise PCAMError(
            ResultCode.DEFINITION_REJECTED,
            PCAMFault.STATE_INVARIANT_FAILURE,
            f"semantic fact requires a direct predicate reference: {value.get('id')}",
        )
    policy = value["hit_policy"]
    return FactBinding(
        fact=SemanticFact(
            fact_id=str(value["id"]),
            direction=str(value["direction"]),  # type: ignore[arg-type]
            channels=tuple(str(item) for item in value.get("channels", ())),
            tags=tuple(str(item) for item in value.get("tags", ())),
            attributes=dict(value.get("attributes", {})),
            effect_templates=tuple(_effect_template(item) for item in value.get("effect_templates", ())),
        ),
        when_predicate=reference.removeprefix(prefix),
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
        reducer=str(value.get("reducer", "ORDERED")),  # type: ignore[arg-type]
        priority=int(value.get("priority", 0)),
        authoritative=bool(value.get("authoritative", True)),
    )


def _transition(value: dict[str, Any]) -> TransitionDefinition:
    target = value["target"]
    input_match = value.get("input_match")
    event_match = value.get("event_match")
    return TransitionDefinition(
        id=str(value["id"]),
        source_node=str(value["source_node"]),
        evaluation_point=str(value["evaluation_point"]),  # type: ignore[arg-type]
        priority=int(value["priority"]),
        target_kind=str(target["kind"]),  # type: ignore[arg-type]
        target_node=target.get("node"),
        target_action=target.get("action"),
        target_step=int(target.get("target_step", 0)),
        source_disposition=str(target.get("source_disposition", "TERMINATE_SOURCE")),  # type: ignore[arg-type]
        child_slot_id=target.get("child_slot_id"),
        parent_policy=target.get("parent_policy"),
        guard_expression=dict(value["guard"]),
        input_command=input_match.get("command_id") if isinstance(input_match, dict) else None,
        event_type=event_match.get("event_type") if isinstance(event_match, dict) else None,
        consume_policy=str(value.get("consume_policy", "ON_ACCEPT")),  # type: ignore[arg-type]
        claims=tuple(_claim(item) for item in value.get("claims", ())),
    )


def _claim(value: dict[str, Any]) -> Claim:
    kind = str(value["kind"])
    key = value.get("resource", value.get("slot", value.get("key")))
    if key is None:
        raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.MISSING_REFERENCE, f"claim key: {kind}")
    return Claim(kind=kind, key=str(key), amount=int(value.get("amount", 1)))  # type: ignore[arg-type]


def _slot_claim(value: dict[str, Any]) -> Claim:
    return Claim("ACTION_SLOT", str(value["slot"]), int(value.get("amount", 1)))


def _operation(value: dict[str, Any]) -> RuleOperation:
    operation = str(value["op"])
    data = {key: item for key, item in value.items() if key != "op"}
    if operation == "APPEND_EFFECT_TEMPLATE":
        effect = data.pop("effect")
        if not isinstance(effect, dict):
            raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.STATE_INVARIANT_FAILURE, operation)
        data["template"] = _effect_template(effect)
    return RuleOperation(operation, data)


def _require_valid(document: dict[str, Any], kind: str) -> None:
    if document.get("kind") != kind:
        raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.INVALID_DOCUMENT, f"expected {kind}")
    diagnostics = validate_document(document)
    if diagnostics:
        first = diagnostics[0]
        raise PCAMError(
            ResultCode.DEFINITION_REJECTED,
            PCAMFault.INVALID_DOCUMENT,
            f"{first.path}: {first.message}",
        )
