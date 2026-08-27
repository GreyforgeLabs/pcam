"""Bounded, declarative PCAM extension registration and validation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from .canonical import canonical_dumps, canonical_hash
from .errors import PCAMError, PCAMFault, ResultCode

NAMESPACE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*(\.[A-Za-z][A-Za-z0-9-]*)+$")
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")


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


def _fault(message: str) -> None:
    raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.INVALID_EXTENSION, message)
