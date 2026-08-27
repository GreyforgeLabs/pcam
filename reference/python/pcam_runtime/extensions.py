"""Bounded, declarative PCAM extension registration and validation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Mapping

from jsonschema import Draft202012Validator

from .canonical import canonical_dumps, canonical_hash
from .errors import PCAMError, PCAMFault, ResultCode

NAMESPACE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*(\.[A-Za-z][A-Za-z0-9-]*)+$")
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
MAX_EXTENSION_DOCUMENT_DEPTH = 64


@dataclass(frozen=True)
class ExtensionRegistration:
    namespace: str
    implementation_id: str
    implementation_hash: str
    authoritative: bool
    schema_id: str
    payload_schema: dict[str, Any]
    canonical_encoding: str = "pcam.cj1.v1"
    validation_id: str = "pcam.validation.json-schema-2020-12"
    runtime_semantics_id: str = "pcam.runtime.declarative"
    ordering_id: str = "pcam.order.namespace"
    fault_behavior_id: str = "pcam.fault.extension"
    snapshot_schema_id: str = "pcam.snapshot.extension-state"
    rollback_behavior_id: str = "pcam.rollback.snapshot-restore"
    determinism_vectors: tuple[str, ...] = ()
    runtime_hook: Literal["TICK_START_COUNTER"] | None = None
    implementation_source: bytes | None = field(default=None, repr=False, compare=False)
    _schema_bytes: bytes = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_namespace(self.namespace)
        for value in (
            self.implementation_id,
            self.canonical_encoding,
            self.validation_id,
            self.runtime_semantics_id,
            self.ordering_id,
            self.fault_behavior_id,
            self.rollback_behavior_id,
        ):
            if not IDENTIFIER.fullmatch(value):
                _fault(f"invalid extension contract identifier: {value}")
        if not self.schema_id or len(self.schema_id) > 512:
            _fault("extension schema_id must contain 1 to 512 characters")
        if not self.snapshot_schema_id or len(self.snapshot_schema_id) > 512:
            _fault("extension snapshot_schema_id must contain 1 to 512 characters")
        if not DIGEST.fullmatch(self.implementation_hash):
            _fault("extension implementation_hash must be lowercase SHA-256")
        if self.authoritative and not self.determinism_vectors:
            _fault("authoritative extension requires determinism vectors")
        if len(set(self.determinism_vectors)) != len(self.determinism_vectors):
            _fault("extension determinism vectors must be unique")
        if any(not DIGEST.fullmatch(value) for value in self.determinism_vectors):
            _fault("extension determinism vector identifiers must be lowercase SHA-256")
        if self.implementation_source is not None and hashlib.sha256(self.implementation_source).hexdigest() != self.implementation_hash:
            _fault("extension implementation source does not match implementation_hash")
        Draft202012Validator.check_schema(self.payload_schema)
        object.__setattr__(self, "_schema_bytes", canonical_dumps(self.payload_schema))

    @property
    def schema_document(self) -> dict[str, Any]:
        return json.loads(self._schema_bytes)

    def identity_record(self) -> dict[str, object]:
        return {
            "authoritative": self.authoritative,
            "canonical_encoding": self.canonical_encoding,
            "determinism_vectors": sorted(self.determinism_vectors),
            "fault_behavior_id": self.fault_behavior_id,
            "implementation_hash": self.implementation_hash,
            "implementation_id": self.implementation_id,
            "runtime_hook": self.runtime_hook,
            "namespace": self.namespace,
            "ordering_id": self.ordering_id,
            "payload_schema": self.schema_document,
            "rollback_behavior_id": self.rollback_behavior_id,
            "runtime_semantics_id": self.runtime_semantics_id,
            "schema_id": self.schema_id,
            "snapshot_schema_id": self.snapshot_schema_id,
            "validation_id": self.validation_id,
        }


@dataclass(frozen=True)
class ExtensionValidation:
    accepted: tuple[str, ...]
    ignored: tuple[str, ...]


@dataclass(frozen=True)
class ExtensionRegistry:
    registrations: tuple[ExtensionRegistration, ...] = ()

    def __post_init__(self) -> None:
        namespaces = [item.namespace for item in self.registrations]
        if len(namespaces) != len(set(namespaces)):
            _fault("extension registry namespaces must be unique")

    @property
    def identity_hash(self) -> str:
        return canonical_hash(
            [
                item.identity_record()
                for item in sorted(self.registrations, key=lambda registration: registration.namespace.encode("utf-8"))
            ]
        )

    def validate(self, declarations: Mapping[str, object], max_bytes: int) -> ExtensionValidation:
        _validate_depth(declarations)
        if len(canonical_dumps(declarations)) > max_bytes:
            raise PCAMError(
                ResultCode.DEFINITION_REJECTED,
                PCAMFault.EXTENSION_LIMIT_EXCEEDED,
                "extension declarations exceed max_extension_state_bytes",
            )
        known = {item.namespace: item for item in self.registrations}
        accepted: list[str] = []
        ignored: list[str] = []
        for namespace in sorted(declarations, key=lambda item: item.encode("utf-8")):
            _validate_namespace(namespace)
            declaration = declarations[namespace]
            if not isinstance(declaration, Mapping):
                _fault(f"extension declaration must be an object: {namespace}")
            requirement = declaration.get("requirement")
            authoritative = declaration.get("authoritative")
            omission_preserves = declaration.get("omission_preserves_authority")
            if requirement not in {"REQUIRED", "OPTIONAL"} or not isinstance(authoritative, bool):
                _fault(f"invalid extension classification: {namespace}")
            if requirement == "OPTIONAL" and (authoritative or omission_preserves is not True):
                _fault(f"optional extension cannot alter authoritative semantics: {namespace}")
            if authoritative and requirement != "REQUIRED":
                _fault(f"authoritative extension must be required: {namespace}")
            registration = known.get(namespace)
            if registration is None:
                if requirement == "REQUIRED":
                    raise PCAMError(
                        ResultCode.DEFINITION_REJECTED,
                        PCAMFault.UNKNOWN_REQUIRED_EXTENSION,
                        namespace,
                    )
                ignored.append(namespace)
                continue
            if authoritative != registration.authoritative:
                _fault(f"extension authority classification mismatch: {namespace}")
            self._validate_contract(namespace, declaration, registration)
            errors = sorted(
                Draft202012Validator(registration.schema_document).iter_errors(declaration.get("payload")),
                key=lambda error: tuple(str(part) for part in error.absolute_path),
            )
            if errors:
                path = ".".join(str(part) for part in errors[0].absolute_path)
                _fault(f"extension payload rejected: {namespace}:{path}:{errors[0].message}")
            accepted.append(namespace)
        return ExtensionValidation(tuple(accepted), tuple(ignored))

    def require_executable(self, declarations: Mapping[str, object], max_bytes: int) -> None:
        validation = self.validate(declarations, max_bytes)
        known = {item.namespace: item for item in self.registrations}
        for namespace in validation.accepted:
            declaration = declarations[namespace]
            if not isinstance(declaration, Mapping) or declaration.get("authoritative") is not True:
                continue
            registration = known[namespace]
            if registration.runtime_hook is None or registration.implementation_source is None:
                _fault(f"authoritative extension has no verified runtime module: {namespace}")

    def apply_tick_start(
        self,
        state: Any,
        declarations: Mapping[str, object],
    ) -> Any:
        extension_state = dict(state.extension_state)
        registrations = {item.namespace: item for item in self.registrations}
        for namespace in sorted(declarations, key=lambda item: item.encode("utf-8")):
            registration = registrations.get(namespace)
            declaration = declarations[namespace]
            if (
                registration is None
                or registration.runtime_hook is None
                or not isinstance(declaration, Mapping)
                or declaration.get("authoritative") is not True
            ):
                continue
            if registration.runtime_hook == "TICK_START_COUNTER":
                payload = declaration.get("payload")
                if not isinstance(payload, Mapping) or type(payload.get("increment")) is not int:
                    raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.INVALID_EXTENSION, namespace)
                increment = int(payload["increment"])
                current = extension_state.get(namespace, {"counter": 0})
                if not isinstance(current, Mapping) or type(current.get("counter")) is not int:
                    raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.INVALID_EXTENSION, namespace)
                counter = int(current["counter"]) + increment
                if not 0 <= counter <= (1 << 64) - 1:
                    raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.INTEGER_OVERFLOW, namespace)
                extension_state[namespace] = {"counter": counter}
        return replace(state, extension_state=extension_state)

    @staticmethod
    def _validate_contract(
        namespace: str,
        declaration: Mapping[str, object],
        registration: ExtensionRegistration,
    ) -> None:
        if not registration.authoritative:
            return
        expected: dict[str, object] = {
            "schema_id": registration.schema_id,
            "canonical_encoding": registration.canonical_encoding,
            "validation_id": registration.validation_id,
            "runtime_semantics_id": registration.runtime_semantics_id,
            "ordering_id": registration.ordering_id,
            "fault_behavior_id": registration.fault_behavior_id,
            "snapshot_schema_id": registration.snapshot_schema_id,
            "rollback_behavior_id": registration.rollback_behavior_id,
            "determinism_vectors": sorted(registration.determinism_vectors),
        }
        for key, expected_value in expected.items():
            actual = declaration.get(key)
            if key == "determinism_vectors" and isinstance(actual, list):
                actual = sorted(actual)
            if actual != expected_value:
                _fault(f"extension contract mismatch: {namespace}:{key}")


def _validate_namespace(namespace: str) -> None:
    if len(namespace) > 128 or not NAMESPACE.fullmatch(namespace):
        _fault(f"invalid extension namespace: {namespace}")


def _validate_depth(value: object) -> None:
    stack = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > MAX_EXTENSION_DOCUMENT_DEPTH:
            raise PCAMError(
                ResultCode.DEFINITION_REJECTED,
                PCAMFault.EXTENSION_LIMIT_EXCEEDED,
                f"extension document depth exceeds {MAX_EXTENSION_DOCUMENT_DEPTH}",
            )
        if isinstance(current, Mapping):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, (list, tuple)):
            stack.extend((item, depth + 1) for item in current)


def _fault(message: str) -> None:
    raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.INVALID_EXTENSION, message)
