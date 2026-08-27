"""Bounded, warning-first PCAM v1/v2 to PCAM-24 draft migration."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .canonical import canonical_hash
from .errors import PCAMError, PCAMFault, ResultCode
from .schema import validate_document

MAX_LEGACY_TAGS = 1024
MAX_LEGACY_RANGES = 4096


@dataclass(frozen=True, order=True)
class MigrationWarning:
    code: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "path": self.path}


@dataclass(frozen=True)
class MigrationResult:
    definition: dict[str, Any]
    source_evidence_hash: str
    source_version: str
    warnings: tuple[MigrationWarning, ...]


def migrate_legacy(document: dict[str, Any]) -> MigrationResult:
    version = _legacy_version(document.get("pcam_version"))
    source_hash = canonical_hash(_legacy_hash_value(document))
    tags = _legacy_tags(document.get("phases", document.get("windows", {})))
    warnings: list[MigrationWarning] = []
    if _has_overlaps(tags):
        warnings.append(
            MigrationWarning(
                "OVERLAPPING_OR_CONTRADICTORY_WINDOWS",
                "$.phases",
                "legacy windows overlap and require semantic review",
            )
        )
    warning_if_missing = (
        ("stall_state", "MISSING_STALL_STATE", "$.stall_state", "legacy source does not define authoritative stall state"),
        ("hit_policy", "MISSING_HIT_POLICY", "$.hit_policy", "legacy source does not define an authoritative hit policy"),
        ("cycle_identity", "MISSING_CYCLE_IDENTITY", "$.cycle_identity", "legacy source does not distinguish cycle identity"),
        ("skip_effects", "UNDEFINED_SKIP_EFFECTS", "$.skip_effects", "legacy source does not define crossed-state skip effects"),
        (
            "nesting_return",
            "UNDEFINED_NESTING_RETURN",
            "$.nesting_return",
            "legacy source does not define parent-child return behavior",
        ),
        (
            "deterministic_limits",
            "MISSING_DETERMINISTIC_LIMITS",
            "$.deterministic_limits",
            "legacy source does not declare deterministic limits",
        ),
    )
    for field, code, path, message in warning_if_missing:
        if field not in document:
            warnings.append(MigrationWarning(code, path, message))
    if "precedence" in document or "property_precedence" in document:
        warnings.append(
            MigrationWarning(
                "UNIVERSAL_PRECEDENCE_ASSUMPTION_REVIEW",
                "$.precedence",
                "legacy global precedence must be replaced by typed directed rules",
            )
        )
    if _contains_phase_only_networking(document.get("networking")):
        warnings.append(
            MigrationWarning(
                "PHASE_ONLY_NETWORKING_REVIEW",
                "$.networking",
                "phase-only networking is not rollback-compatible PCAM v3 state",
            )
        )
    rate, timing_warning = _legacy_rate(document.get("rate"))
    if timing_warning:
        warnings.append(
            MigrationWarning(
                "FLOATING_TIMING_REVIEW",
                "$.rate",
                "floating or invalid legacy timing was replaced by a one-quantum-per-tick draft rate",
            )
        )
    lifecycle = document.get("lifecycle", "TERMINATE")
    if lifecycle not in {"TERMINATE", "LOOP", "CLAMP"}:
        lifecycle = "TERMINATE"
        warnings.append(
            MigrationWarning(
                "UNSUPPORTED_LIFECYCLE_DEFAULTED",
                "$.lifecycle",
                "unsupported legacy lifecycle was replaced with TERMINATE",
            )
        )
    warnings.append(
        MigrationWarning(
            "MANUAL_REVIEW_REQUIRED",
            "$",
            "migration output is a draft PCAM-24 source and is not normative until reviewed",
        )
    )
    migrated = {
        "pcam_version": "3.0",
        "kind": "pcam24",
        "id": str(document.get("id", "Legacy.imported")),
        "revision": 1,
        "lifecycle": lifecycle,
        "rate": rate,
        "tags": tags,
        "metadata": {
            "manual_review_required": True,
            "migrated_from": version,
            "source_evidence_hash": source_hash,
            "wire_compatible": False,
        },
        "extensions": {},
    }
    diagnostics = validate_document(migrated)
    if diagnostics:
        first = diagnostics[0]
        raise PCAMError(
            ResultCode.DEFINITION_REJECTED,
            PCAMFault.INVALID_DOCUMENT,
            f"migrated definition rejected at {first.path}: {first.message}",
        )
    return MigrationResult(
        migrated,
        source_hash,
        version,
        tuple(sorted(warnings, key=lambda item: (item.code, item.path, item.message))),
    )


def _legacy_version(value: object) -> str:
    normalized = None
    if type(value) is int and value in {1, 2}:
        normalized = str(value)
    elif type(value) is float and value in {1.0, 2.0}:
        normalized = str(int(value))
    elif isinstance(value, str) and value in {"1", "1.0", "2", "2.0"}:
        normalized = value[0]
    if normalized is None:
        raise PCAMError(
            ResultCode.DEFINITION_REJECTED,
            PCAMFault.UNSUPPORTED_LEGACY_VERSION,
            f"migrate-v2 accepts only explicit PCAM v1 or v2 input, got {value!r}",
        )
    return normalized


def _legacy_tags(value: object) -> dict[str, list[list[int]]]:
    if not isinstance(value, dict) or len(value) > MAX_LEGACY_TAGS:
        raise PCAMError(
            ResultCode.DEFINITION_REJECTED,
            PCAMFault.INVALID_DOCUMENT,
            "legacy phases must be a bounded object",
        )
    tags: dict[str, list[list[int]]] = {}
    total = 0
    for name, ranges in sorted(value.items(), key=lambda item: str(item[0]).encode("utf-8")):
        if not isinstance(ranges, list):
            raise _invalid_range(str(name))
        converted: list[list[int]] = []
        for pair in ranges:
            total += 1
            if total > MAX_LEGACY_RANGES:
                raise PCAMError(
                    ResultCode.DEFINITION_REJECTED,
                    PCAMFault.INVALID_DOCUMENT,
                    "legacy phase range count exceeds limit",
                )
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or type(pair[0]) is not int
                or type(pair[1]) is not int
                or not 0 <= pair[0] < pair[1] <= 24
            ):
                raise _invalid_range(str(name))
            converted.append([pair[0], pair[1]])
        tags[str(name)] = converted
    return tags


def _has_overlaps(tags: dict[str, list[list[int]]]) -> bool:
    intervals = [
        (start, end, tag)
        for tag, ranges in tags.items()
        for start, end in ranges
    ]
    ordered = sorted(intervals, key=lambda item: (item[0], item[1], item[2].encode("utf-8")))
    return any(left[1] > right[0] for left, right in zip(ordered, ordered[1:]))


def _legacy_rate(value: object) -> tuple[dict[str, int], bool]:
    if isinstance(value, dict):
        scale = value.get("scale")
        units = value.get("units_per_tick")
        if type(scale) is int and type(units) is int and scale > 0 and units >= 0:
            return {"scale": scale, "units_per_tick": units}, False
    return {"scale": 1, "units_per_tick": 1}, True


def _contains_phase_only_networking(value: object) -> bool:
    if isinstance(value, str):
        return "phase" in value.lower()
    if isinstance(value, dict):
        return any(_contains_phase_only_networking(key) or _contains_phase_only_networking(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_phase_only_networking(item) for item in value)
    return False


def _legacy_hash_value(value: object) -> object:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.INVALID_DOCUMENT, "non-finite legacy number")
        return {"$legacy_float": format(value, ".17g")}
    if isinstance(value, dict):
        return {str(key): _legacy_hash_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_legacy_hash_value(item) for item in value]
    return value


def _invalid_range(name: str) -> PCAMError:
    return PCAMError(
        ResultCode.DEFINITION_REJECTED,
        PCAMFault.INVALID_PROFILE_RANGE,
        f"legacy phase range is invalid or wrapping: {name}",
    )
