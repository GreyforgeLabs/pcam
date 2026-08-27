"""Directed typed interaction-rule pipeline over a frozen semantic snapshot."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from .effects import EffectEnvelope
from .errors import PCAMError, PCAMFault, ResultCode
from .expressions import evaluate
from .immutable import freeze_value
from .numeric import scale_ratio

Stage = Literal["ADMISSION", "ROUTING", "MODIFICATION", "MATERIALIZATION", "REACTION"]
STAGES: tuple[Stage, ...] = ("ADMISSION", "ROUTING", "MODIFICATION", "MATERIALIZATION", "REACTION")


@dataclass(frozen=True)
class EffectTemplate:
    effect_type: str
    effect_class: str
    payload: object
    reducer: str = "ORDERED"
    priority: int = 0
    authoritative: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", freeze_value(self.payload))


@dataclass(frozen=True)
class SemanticFact:
    fact_id: str
    direction: Literal["OFFENSE", "DEFENSE", "NEUTRAL"]
    channels: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    attributes: dict[str, object] | None = None
    effect_templates: tuple[EffectTemplate, ...] = ()

    def __post_init__(self) -> None:
        if self.attributes is not None:
            object.__setattr__(self, "attributes", freeze_value(self.attributes))


@dataclass(frozen=True)
class InteractionCandidate:
    tick: int
    candidate_id: str
    source_entity_id: int
    target_entity_id: int
    source_action_instance_id: int
    offense_fact_id: str
    contact_id: str
    contact_partition: str = "default"
    host_context: dict[str, object] | None = None
    defense_fact_id: str | None = None

    def __post_init__(self) -> None:
        if self.host_context is not None:
            object.__setattr__(self, "host_context", freeze_value(self.host_context))


@dataclass(frozen=True)
class RuleOperation:
    op: str
    data: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if self.data is not None:
            object.__setattr__(self, "data", freeze_value(self.data))


@dataclass(frozen=True)
class InteractionRule:
    rule_id: str
    stage: Stage
    order: int
    condition: dict[str, object]
    operations: tuple[RuleOperation, ...]
    stop_stage: bool = False
    stop_pipeline: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "condition", freeze_value(self.condition))


@dataclass(frozen=True)
class InteractionDecision:
    candidate_id: str
    status: Literal["ACCEPTED", "REJECTED"]
    current_target: int
    active_effect_templates: tuple[EffectTemplate, ...]
    decision_tags: tuple[str, ...]
    generated_effects: tuple[EffectEnvelope, ...]
    receipt_requests: tuple[str, ...]
    redirect_count: int
    visited_targets: tuple[int, ...]
    trace: tuple[dict[str, object], ...]


def canonical_candidates(candidates: tuple[InteractionCandidate, ...]) -> tuple[InteractionCandidate, ...]:
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.source_entity_id,
                item.target_entity_id,
                item.source_action_instance_id,
                item.offense_fact_id.encode("utf-8"),
                (item.defense_fact_id or "").encode("utf-8"),
                item.contact_partition.encode("utf-8"),
                item.contact_id.encode("utf-8"),
                item.candidate_id.encode("utf-8"),
            ),
        )
    )


def validate_rules(rules: tuple[InteractionRule, ...]) -> None:
    seen: set[tuple[Stage, int]] = set()
    for rule in rules:
        key = (rule.stage, rule.order)
        if key in seen:
            raise PCAMError(
                ResultCode.DEFINITION_REJECTED,
                PCAMFault.STATE_INVARIANT_FAILURE,
                f"duplicate interaction-rule order {rule.stage}:{rule.order}",
            )
        seen.add(key)


def resolve_candidate(
    candidate: InteractionCandidate,
    offense: SemanticFact,
    defense_by_target: dict[int, SemanticFact | None],
    rules: tuple[InteractionRule, ...],
    max_redirects: int = 8,
    redirect_limit_policy: Literal["FAULT", "REJECT"] = "FAULT",
    max_expression_depth: int = 64,
    max_expression_nodes: int = 4096,
) -> InteractionDecision:
    validate_rules(rules)
    ordered_rules = tuple(sorted(rules, key=lambda item: (STAGES.index(item.stage), item.order)))
    status: Literal["ACCEPTED", "REJECTED"] = "ACCEPTED"
    current_target = candidate.target_entity_id
    templates = list(offense.effect_templates)
    tags: set[str] = set()
    generated: list[EffectEnvelope] = []
    receipts: list[str] = []
    redirect_count = 0
    visited = [current_target]
    trace: list[dict[str, object]] = []
    restart = True
    pipeline_stopped = False

    while restart and not pipeline_stopped:
        restart = False
        defense = defense_by_target.get(current_target)
        for stage in STAGES:
            stop_stage = False
            for rule in (item for item in ordered_rules if item.stage == stage):
                context = _context(candidate, current_target, offense, defense, status, tags)
                if evaluate(
                    rule.condition,
                    context,
                    max_depth=max_expression_depth,
                    max_nodes=max_expression_nodes,
                ) is not True:
                    continue
                trace.append({"rule_id": rule.rule_id, "stage": stage, "order": rule.order})
                for operation_index, operation in enumerate(rule.operations):
                    data = operation.data or {}
                    if operation.op == "REJECT":
                        status = "REJECTED"
                        tags.add(str(data.get("reason", "REJECTED")))
                    elif operation.op == "REDIRECT":
                        target = int(data["target_entity_id"])
                        if target in visited or redirect_count >= max_redirects:
                            if redirect_limit_policy == "REJECT":
                                status = "REJECTED"
                                tags.add("REDIRECT_LIMIT_EXCEEDED")
                                pipeline_stopped = True
                                break
                            raise PCAMError(
                                ResultCode.RUNTIME_FAULT,
                                PCAMFault.REDIRECT_LIMIT_EXCEEDED,
                                candidate.candidate_id,
                            )
                        current_target = target
                        visited.append(target)
                        redirect_count += 1
                        restart = True
                        stop_stage = True
                        break
                    elif operation.op == "REMOVE_EFFECT_CLASS":
                        effect_class = str(data["effect_class"])
                        templates = [item for item in templates if item.effect_class != effect_class]
                    elif operation.op == "SCALE_EFFECT_CLASS":
                        effect_class = str(data["effect_class"])
                        numerator = int(data["numerator"])
                        denominator = int(data["denominator"])
                        templates = [
                            replace(item, payload=scale_ratio(_integer_payload(item), numerator, denominator))
                            if item.effect_class == effect_class
                            else item
                            for item in templates
                        ]
                    elif operation.op == "CAP_EFFECT_CLASS":
                        effect_class = str(data["effect_class"])
                        cap = int(data["cap"])
                        templates = [
                            replace(item, payload=min(_integer_payload(item), cap))
                            if item.effect_class == effect_class
                            else item
                            for item in templates
                        ]
                    elif operation.op == "REPLACE_EFFECT_CLASS":
                        effect_class = str(data["effect_class"])
                        replacement = data["replacement"]
                        if not isinstance(replacement, EffectTemplate):
                            raise _fault("replacement must be an EffectTemplate")
                        templates = [replacement if item.effect_class == effect_class else item for item in templates]
                    elif operation.op == "APPEND_EFFECT_TEMPLATE":
                        template = data["template"]
                        if not isinstance(template, EffectTemplate):
                            raise _fault("appended template must be an EffectTemplate")
                        templates.append(
                            replace(
                                template,
                                payload=_resolve_payload(
                                    template.payload,
                                    context,
                                    max_expression_depth,
                                    max_expression_nodes,
                                ),
                            )
                        )
                    elif operation.op == "ADD_DECISION_TAG":
                        tags.add(str(data["tag"]))
                    elif operation.op == "REQUEST_RECEIPT":
                        receipts.append(str(data["condition"]))
                    elif operation.op == "MATERIALIZE":
                        statuses = _materialize_list(
                            data.get("statuses", ("ACCEPTED",)),
                            "statuses",
                        )
                        if not set(statuses).issubset({"ACCEPTED", "REJECTED"}):
                            raise _fault("materialization statuses contain an unknown status")
                        effect_classes = _materialize_list(
                            data.get("effect_classes", ()),
                            "effect_classes",
                            allow_empty=True,
                        )
                        selected = [
                            template
                            for template in templates
                            if not effect_classes or template.effect_class in effect_classes
                        ]
                        if status == "REJECTED" and status in statuses:
                            if not effect_classes or any(template.effect_class != "REACTION" for template in selected):
                                raise _fault(
                                    "rejected materialization requires explicit REACTION effect classes"
                                )
                        if status in statuses:
                            generated.extend(
                                _materialize(candidate, current_target, selected, rule.rule_id, operation_index)
                            )
                    elif operation.op == "STOP_STAGE":
                        stop_stage = True
                        break
                    elif operation.op == "STOP_PIPELINE":
                        pipeline_stopped = True
                        break
                    else:
                        raise _fault(f"unknown interaction operation: {operation.op}")
                if restart or pipeline_stopped:
                    break
                if rule.stop_pipeline:
                    pipeline_stopped = True
                    break
                if rule.stop_stage:
                    stop_stage = True
                if stop_stage:
                    break
            if restart or pipeline_stopped:
                break

    return InteractionDecision(
        candidate_id=candidate.candidate_id,
        status=status,
        current_target=current_target,
        active_effect_templates=tuple(templates),
        decision_tags=tuple(sorted(tags, key=lambda item: item.encode("utf-8"))),
        generated_effects=tuple(generated),
        receipt_requests=tuple(receipts),
        redirect_count=redirect_count,
        visited_targets=tuple(visited),
        trace=tuple(trace),
    )


def _context(
    candidate: InteractionCandidate,
    current_target: int,
    offense: SemanticFact,
    defense: SemanticFact | None,
    status: str,
    tags: set[str],
) -> dict[str, object]:
    host_context = candidate.host_context or {}
    return {
        "candidate.candidate_id": candidate.candidate_id,
        "candidate.source_entity_id": candidate.source_entity_id,
        "candidate.target_entity_id": current_target,
        "candidate.source_action_instance_id": candidate.source_action_instance_id,
        "candidate.offense_fact_id": candidate.offense_fact_id,
        "candidate.defense_fact_id": candidate.defense_fact_id,
        "offense.channels": frozenset(offense.channels),
        "offense.tags": frozenset(offense.tags),
        "offense.fact_id": offense.fact_id,
        "defense.channels": frozenset(defense.channels if defense else ()),
        "defense.tags": frozenset(defense.tags if defense else ()),
        "defense.fact_id": defense.fact_id if defense else None,
        "target.lifecycle": host_context.get("target.lifecycle", "RUNNING"),
        "decision.status": status,
        "decision.tags": frozenset(tags),
    }


def _resolve_payload(
    payload: object,
    context: dict[str, object],
    max_expression_depth: int,
    max_expression_nodes: int,
) -> object:
    if isinstance(payload, dict):
        if set(payload) in ({"literal"}, {"ref"}, {"op", "args"}):
            return evaluate(
                payload,
                context,
                max_depth=max_expression_depth,
                max_nodes=max_expression_nodes,
            )
        return {
            key: _resolve_payload(value, context, max_expression_depth, max_expression_nodes)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [
            _resolve_payload(value, context, max_expression_depth, max_expression_nodes)
            for value in payload
        ]
    return payload


def _materialize(
    candidate: InteractionCandidate,
    current_target: int,
    templates: list[EffectTemplate],
    rule_id: str,
    operation_index: int,
) -> list[EffectEnvelope]:
    return [
        EffectEnvelope(
            effect_id=(
                f"{candidate.tick}:{candidate.source_action_instance_id}:"
                f"{candidate.candidate_id}:{rule_id}:{operation_index}:{index}"
            ),
            effect_type=template.effect_type,
            effect_class=template.effect_class,
            source_entity_id=candidate.source_entity_id,
            target_entity_id=current_target,
            source_action_instance_id=candidate.source_action_instance_id,
            origin_tick=candidate.tick,
            priority=template.priority,
            payload=template.payload,
            reducer=template.reducer,  # type: ignore[arg-type]
            authoritative=template.authoritative,
        )
        for index, template in enumerate(templates)
    ]


def _materialize_list(
    value: object,
    field: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise _fault(f"materialization {field} must be a list")
    items = tuple(value)
    if (not items and not allow_empty) or any(type(item) is not str or not item for item in items):
        raise _fault(f"materialization {field} must contain nonempty strings")
    if len(set(items)) != len(items):
        raise _fault(f"materialization {field} must not contain duplicates")
    return items


def _integer_payload(template: EffectTemplate) -> int:
    if type(template.payload) is not int:
        raise _fault(f"{template.effect_type} requires an integer payload")
    return template.payload


def _fault(message: str) -> PCAMError:
    return PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, message)
