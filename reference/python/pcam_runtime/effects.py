"""Canonical effect ordering, reduction, and rejection tracing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from .errors import PCAMError, PCAMFault, ResultCode
from .numeric import add_i64

Reducer = Literal["SUM", "MIN", "MAX", "SET_UNION", "ORDERED", "FIRST", "LAST", "EXCLUSIVE", "CUSTOM_DETERMINISTIC"]


@dataclass(frozen=True)
class EffectEnvelope:
    effect_id: str
    effect_type: str
    effect_class: str
    source_entity_id: int
    target_entity_id: int
    source_action_instance_id: int
    origin_tick: int
    priority: int
    payload: object
    reducer: Reducer
    authoritative: bool = True


@dataclass(frozen=True)
class ReducedEffect:
    target_entity_id: int
    effect_type: str
    reducer: Reducer
    value: object
    source_effect_ids: tuple[str, ...]


@dataclass(frozen=True)
class RejectedEffect:
    effect_id: str
    reason: str


CustomReducer = Callable[[tuple[EffectEnvelope, ...]], object]


def canonical_effects(effects: tuple[EffectEnvelope, ...]) -> tuple[EffectEnvelope, ...]:
    return tuple(
        sorted(
            effects,
            key=lambda item: (
                item.target_entity_id,
                item.effect_type.encode("utf-8"),
                -item.priority,
                item.source_entity_id,
                item.source_action_instance_id,
                item.effect_id.encode("utf-8"),
            ),
        )
    )


def reduce_effects(
    effects: tuple[EffectEnvelope, ...],
    custom_reducers: dict[str, CustomReducer] | None = None,
) -> tuple[tuple[ReducedEffect, ...], tuple[RejectedEffect, ...]]:
    groups: dict[tuple[int, str], list[EffectEnvelope]] = {}
    for effect in canonical_effects(effects):
        groups.setdefault((effect.target_entity_id, effect.effect_type), []).append(effect)
    reduced: list[ReducedEffect] = []
    rejected: list[RejectedEffect] = []
    for (target, effect_type), values in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1].encode("utf-8"))):
        ordered = tuple(values)
        reducers = {item.reducer for item in ordered}
        if len(reducers) != 1:
            raise _fault(effect_type, "effect type mixes reducers")
        reducer = ordered[0].reducer
        payload, group_rejections = _reduce_group(effect_type, reducer, ordered, custom_reducers or {})
        reduced.append(ReducedEffect(target, effect_type, reducer, payload, tuple(item.effect_id for item in ordered)))
        rejected.extend(group_rejections)
    return tuple(reduced), tuple(rejected)


def _reduce_group(
    effect_type: str,
    reducer: Reducer,
    effects: tuple[EffectEnvelope, ...],
    custom_reducers: dict[str, CustomReducer],
) -> tuple[object, tuple[RejectedEffect, ...]]:
    payloads = tuple(item.payload for item in effects)
    if reducer == "SUM":
        total = 0
        for payload in payloads:
            total = add_i64(total, _integer_payload(effect_type, payload))
        return total, ()
    if reducer == "MIN":
        return min(_integer_payload(effect_type, item) for item in payloads), ()
    if reducer == "MAX":
        return max(_integer_payload(effect_type, item) for item in payloads), ()
    if reducer == "SET_UNION":
        union: set[str] = set()
        for payload in payloads:
            if not isinstance(payload, (list, tuple, set, frozenset)) or any(not isinstance(item, str) for item in payload):
                raise _fault(effect_type, "SET_UNION payload must contain symbols")
            union.update(payload)
        return tuple(sorted(union, key=lambda item: item.encode("utf-8"))), ()
    if reducer == "ORDERED":
        return payloads, ()
    if reducer == "FIRST":
        return payloads[0], ()
    if reducer == "LAST":
        return payloads[-1], ()
    if reducer == "EXCLUSIVE":
        rejected = tuple(RejectedEffect(item.effect_id, "EXCLUSIVE_EFFECT_LOST") for item in effects[1:])
        return payloads[0], rejected
    callback = custom_reducers.get(effect_type)
    if callback is None:
        raise _fault(effect_type, "CUSTOM_DETERMINISTIC reducer is not registered")
    return callback(effects), ()


def _integer_payload(effect_type: str, payload: object) -> int:
    if type(payload) is not int:
        raise _fault(effect_type, "integer reducer received non-integer payload")
    return payload


def _fault(effect_type: str, message: str) -> PCAMError:
    return PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.UNKNOWN_EFFECT, f"{effect_type}: {message}")
