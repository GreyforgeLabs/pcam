"""Canonical effect ordering, reduction, and rejection tracing."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from jsonschema import Draft202012Validator

from .canonical import canonical_dumps, canonical_hash
from .errors import PCAMError, PCAMFault, ResultCode
from .numeric import add_i64, mul_i64

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


CUSTOM_ORDERED_I64_FOLD_ID = "greyforge.effect.ordered-i64-fold.v1"
CUSTOM_ORDERED_I64_FOLD_HASH = "6316bc089aaf70e9db41fc7556475b8213181b68da9eddd980b8d1971f632a35"
CUSTOM_ORDERED_I64_FOLD_SEMANTICS = "pcam.runtime.custom.ordered-i64-fold.v1"
CUSTOM_ORDERING = "pcam.order.canonical-effect.v1"
CUSTOM_OVERFLOW = "pcam.overflow.checked-i64.v1"
CUSTOM_SAVE_RESTORE = "pcam.save.stateless.v1"
CUSTOM_ROLLBACK = "pcam.rollback.snapshot-restore.v1"
DIGEST = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")


@dataclass(frozen=True)
class CustomEffectRegistration:
    effect_type: str
    implementation_id: str
    implementation_hash: str
    payload_schema: dict[str, Any]
    determinism_vectors: tuple[str, ...]
    reducer: Literal["CUSTOM_DETERMINISTIC"] = "CUSTOM_DETERMINISTIC"
    runtime_semantics_id: str = CUSTOM_ORDERED_I64_FOLD_SEMANTICS
    ordering_id: str = CUSTOM_ORDERING
    overflow_behavior_id: str = CUSTOM_OVERFLOW
    save_restore_id: str = CUSTOM_SAVE_RESTORE
    rollback_behavior_id: str = CUSTOM_ROLLBACK
    implementation_source: bytes | None = field(default=None, repr=False, compare=False)
    _schema_bytes: bytes = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not IDENTIFIER.fullmatch(self.effect_type):
            _registration_fault("custom effect_type must be a canonical identifier")
        if self.implementation_id != CUSTOM_ORDERED_I64_FOLD_ID:
            _registration_fault("unsupported custom effect implementation_id")
        if self.implementation_hash != CUSTOM_ORDERED_I64_FOLD_HASH:
            _registration_fault("custom effect implementation_hash does not match the executable reducer")
        expected_contract = (
            (self.reducer, "CUSTOM_DETERMINISTIC", "reducer"),
            (self.runtime_semantics_id, CUSTOM_ORDERED_I64_FOLD_SEMANTICS, "runtime_semantics_id"),
            (self.ordering_id, CUSTOM_ORDERING, "ordering_id"),
            (self.overflow_behavior_id, CUSTOM_OVERFLOW, "overflow_behavior_id"),
            (self.save_restore_id, CUSTOM_SAVE_RESTORE, "save_restore_id"),
            (self.rollback_behavior_id, CUSTOM_ROLLBACK, "rollback_behavior_id"),
        )
        for actual, expected, field_name in expected_contract:
            if actual != expected:
                _registration_fault(f"unsupported custom effect {field_name}")
        if not self.determinism_vectors or len(set(self.determinism_vectors)) != len(self.determinism_vectors):
            _registration_fault("custom effect requires unique determinism vectors")
        if any(not DIGEST.fullmatch(value) for value in self.determinism_vectors):
            _registration_fault("custom effect determinism vector identifiers must be lowercase SHA-256")
        if self.payload_schema != {"type": "integer"}:
            _registration_fault("ordered I64 fold requires the canonical integer payload schema")
        if self.implementation_source is None:
            _registration_fault("custom effect requires verified implementation source")
        if hashlib.sha256(self.implementation_source).hexdigest() != self.implementation_hash:
            _registration_fault("custom effect implementation source does not match implementation_hash")
        Draft202012Validator.check_schema(self.payload_schema)
        object.__setattr__(self, "_schema_bytes", canonical_dumps(self.payload_schema))

    @property
    def schema_document(self) -> dict[str, Any]:
        import json

        return json.loads(self._schema_bytes)

    def identity_record(self) -> dict[str, object]:
        return {
            "determinism_vectors": sorted(self.determinism_vectors),
            "effect_type": self.effect_type,
            "implementation_hash": self.implementation_hash,
            "implementation_id": self.implementation_id,
            "ordering_id": self.ordering_id,
            "overflow_behavior_id": self.overflow_behavior_id,
            "payload_schema": self.schema_document,
            "reducer": self.reducer,
            "rollback_behavior_id": self.rollback_behavior_id,
            "runtime_semantics_id": self.runtime_semantics_id,
            "save_restore_id": self.save_restore_id,
        }

    def reduce(self, effects: tuple[EffectEnvelope, ...]) -> int:
        validator = Draft202012Validator(self.schema_document)
        accumulator = 0
        for effect in effects:
            if tuple(validator.iter_errors(effect.payload)):
                raise _fault(self.effect_type, "custom effect payload rejected")
            accumulator = add_i64(mul_i64(accumulator, 10), _integer_payload(self.effect_type, effect.payload))
        return accumulator


@dataclass(frozen=True)
class CustomEffectRegistry:
    registrations: tuple[CustomEffectRegistration, ...] = ()

    def __post_init__(self) -> None:
        effect_types = [item.effect_type for item in self.registrations]
        if len(effect_types) != len(set(effect_types)):
            _registration_fault("custom effect registry effect types must be unique")

    @property
    def identity_hash(self) -> str:
        return canonical_hash(
            [
                item.identity_record()
                for item in sorted(self.registrations, key=lambda item: item.effect_type.encode("utf-8"))
            ]
        )

    def reduce(self, effect_type: str, effects: tuple[EffectEnvelope, ...]) -> object:
        registration = next((item for item in self.registrations if item.effect_type == effect_type), None)
        if registration is None:
            raise _fault(effect_type, "CUSTOM_DETERMINISTIC reducer is not registered")
        return registration.reduce(effects)


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
    custom_registry: CustomEffectRegistry | None = None,
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
        payload, group_rejections = _reduce_group(effect_type, reducer, ordered, custom_registry or CustomEffectRegistry())
        reduced.append(ReducedEffect(target, effect_type, reducer, payload, tuple(item.effect_id for item in ordered)))
        rejected.extend(group_rejections)
    return tuple(reduced), tuple(rejected)


def _reduce_group(
    effect_type: str,
    reducer: Reducer,
    effects: tuple[EffectEnvelope, ...],
    custom_registry: CustomEffectRegistry,
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
    return custom_registry.reduce(effect_type, effects), ()


def _integer_payload(effect_type: str, payload: object) -> int:
    if type(payload) is not int:
        raise _fault(effect_type, "integer reducer received non-integer payload")
    return payload


def _fault(effect_type: str, message: str) -> PCAMError:
    return PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.UNKNOWN_EFFECT, f"{effect_type}: {message}")


def _registration_fault(message: str) -> None:
    raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.UNKNOWN_EFFECT, message)
