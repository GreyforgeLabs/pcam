"""Machine-readable schema and semantic definition validation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, RefResolver

from .errors import PCAMFault, ResultCode

IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
KIND_TO_SCHEMA = {
    "action": "action.schema.json",
    "interaction_profile": "interaction-profile.schema.json",
    "runtime_profile": "runtime-profile.schema.json",
    "pcam24": "pcam24.schema.json",
    "snapshot": "snapshot.schema.json",
}


@dataclass(frozen=True, order=True)
class Diagnostic:
    code: str
    path: str
    message: str
    fault: str = PCAMFault.INVALID_DOCUMENT.value

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "fault": self.fault,
            "message": self.message,
            "path": self.path,
        }


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_document(path: str | Path, max_bytes: int = 1_048_576) -> Any:
    source = Path(path)
    size = source.stat().st_size
    if size > max_bytes:
        raise ValueError(f"document exceeds maximum size of {max_bytes} bytes")
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() in {".yaml", ".yml"}:
        return yaml.safe_load(text)
    return json.loads(text)


def validate_document(document: Any, schema_dir: Path | None = None) -> list[Diagnostic]:
    if not isinstance(document, dict):
        return [Diagnostic(ResultCode.SCHEMA_VALIDATION_FAILED.value, "$", "top-level value must be an object")]
    kind = document.get("kind")
    if kind is None and "definition_set_hash" in document:
        kind = "snapshot"
    schema_name = KIND_TO_SCHEMA.get(str(kind))
    if schema_name is None:
        return [
            Diagnostic(
                ResultCode.DEFINITION_REJECTED.value,
                "$.kind",
                f"unsupported definition kind: {kind!r}",
                PCAMFault.UNSUPPORTED_DEFINITION_KIND.value,
            )
        ]
    schemas = schema_dir or repository_root() / "schemas"
    loaded: dict[str, dict[str, Any]] = {}
    for path in sorted(schemas.glob("*.schema.json")):
        parsed = json.loads(path.read_text(encoding="utf-8"))
        loaded[str(parsed["$id"])] = parsed
        loaded[path.name] = parsed
    schema = loaded[schema_name]
    resolver = RefResolver.from_schema(schema, store=loaded)
    validator = Draft202012Validator(schema, resolver=resolver)
    diagnostics = [
        Diagnostic(
            ResultCode.SCHEMA_VALIDATION_FAILED.value,
            _json_path(error.absolute_path),
            error.message,
        )
        for error in validator.iter_errors(document)
    ]
    if not diagnostics:
        diagnostics.extend(_semantic_diagnostics(str(kind), document))
    return sorted(diagnostics)


def _semantic_diagnostics(kind: str, document: dict[str, Any]) -> list[Diagnostic]:
    if kind == "action":
        return _action_diagnostics(document)
    if kind == "interaction_profile":
        return _interaction_diagnostics(document)
    if kind == "runtime_profile":
        return _runtime_profile_diagnostics(document)
    if kind == "pcam24":
        return _pcam24_diagnostics(document)
    return []


def _action_diagnostics(document: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    nodes = document.get("nodes", {})
    predicates = document.get("predicates", {})
    transitions = document.get("transitions", [])
    for node_name, node in nodes.items():
        if node.get("id") != node_name:
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.nodes.{node_name}.id",
                    "node id must equal its map key",
                    PCAMFault.MISSING_REFERENCE.value,
                )
            )
        if node.get("mode") == "TIMED":
            duration = node.get("duration_quanta")
            if not isinstance(duration, int) or duration <= 0:
                diagnostics.append(
                    Diagnostic(
                        ResultCode.DEFINITION_REJECTED.value,
                        f"$.nodes.{node_name}.duration_quanta",
                        "timed node duration must be a positive integer",
                        PCAMFault.INVALID_NODE_DURATION.value,
                    )
                )
    seen_priorities: set[tuple[str, str, int]] = set()
    completion_sources: set[str] = set()
    for index, transition in enumerate(transitions):
        if not isinstance(transition, dict):
            continue
        source = transition.get("source_node")
        point = transition.get("evaluation_point")
        priority = transition.get("priority")
        if source not in nodes:
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.transitions[{index}].source_node",
                    f"unknown source node: {source!r}",
                    PCAMFault.MISSING_REFERENCE.value,
                )
            )
        if isinstance(priority, int):
            key = (str(source), str(point), priority)
            if key in seen_priorities:
                diagnostics.append(
                    Diagnostic(
                        ResultCode.DEFINITION_REJECTED.value,
                        f"$.transitions[{index}].priority",
                        "transition priority duplicates another transition at the same source and evaluation point",
                        "DUPLICATE_TRANSITION_PRIORITY",
                    )
                )
            seen_priorities.add(key)
        if point == "AFTER_QUANTUM":
            completion_sources.add(str(source))
        target = transition.get("target", {})
        if isinstance(target, dict) and target.get("kind") == "NODE" and target.get("node") not in nodes:
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.transitions[{index}].target.node",
                    f"unknown target node: {target.get('node')!r}",
                    PCAMFault.MISSING_REFERENCE.value,
                )
            )
    for node_name, node in nodes.items():
        if node.get("mode") == "TIMED" and node_name not in completion_sources:
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.nodes.{node_name}",
                    "timed node has no AFTER_QUANTUM completion path",
                    PCAMFault.MISSING_COMPLETION_PATH.value,
                )
            )
    graph = {name: _predicate_dependencies(value.get("expression"), set(predicates)) for name, value in predicates.items()}
    cycle = _first_cycle(graph)
    if cycle:
        diagnostics.append(
            Diagnostic(
                ResultCode.DEFINITION_REJECTED.value,
                f"$.predicates.{cycle[0]}.expression",
                "predicate dependency cycle: " + " -> ".join(cycle),
                PCAMFault.PREDICATE_CYCLE.value,
            )
        )
    return diagnostics


def _interaction_diagnostics(document: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    seen: set[tuple[str, int]] = set()
    for index, rule in enumerate(document.get("rules", [])):
        key = (str(rule.get("stage")), int(rule.get("order", -1)))
        if key in seen:
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.rules[{index}].order",
                    "rule order must be unique within a stage",
                    "DUPLICATE_RULE_ORDER",
                )
            )
        seen.add(key)
    return diagnostics


def _runtime_profile_diagnostics(document: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    seen: set[str] = set()
    for index, profile in enumerate(document.get("network_profiles", [])):
        profile_id = str(profile.get("id"))
        if profile_id in seen:
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.network_profiles[{index}].id",
                    "network profile identifier must be unique",
                    PCAMFault.DUPLICATE_IDENTIFIER.value,
                )
            )
        seen.add(profile_id)
    return diagnostics


def _pcam24_diagnostics(document: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for tag, ranges in document.get("tags", {}).items():
        for index, pair in enumerate(ranges):
            if pair[0] >= pair[1]:
                diagnostics.append(
                    Diagnostic(
                        ResultCode.DEFINITION_REJECTED.value,
                        f"$.tags.{tag}[{index}]",
                        "PCAM-24 ranges must be non-wrapping half-open intervals with start < end",
                        PCAMFault.INVALID_PROFILE_RANGE.value,
                    )
                )
    return diagnostics


def _predicate_dependencies(expression: Any, names: set[str]) -> set[str]:
    dependencies: set[str] = set()
    if isinstance(expression, dict):
        reference = expression.get("ref")
        prefix = "action.predicate."
        if isinstance(reference, str) and reference.startswith(prefix):
            name = reference[len(prefix) :]
            if name in names:
                dependencies.add(name)
        for value in expression.values():
            dependencies.update(_predicate_dependencies(value, names))
    elif isinstance(expression, list):
        for value in expression:
            dependencies.update(_predicate_dependencies(value, names))
    return dependencies


def _first_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(node: str) -> list[str] | None:
        if node in visiting:
            start = visiting.index(node)
            return [*visiting[start:], node]
        if node in visited:
            return None
        visiting.append(node)
        for neighbor in sorted(graph.get(node, ())):
            cycle = visit(neighbor)
            if cycle:
                return cycle
        visiting.pop()
        visited.add(node)
        return None

    for node in sorted(graph):
        cycle = visit(node)
        if cycle:
            return cycle
    return None


def _json_path(path: Any) -> str:
    result = "$"
    for item in path:
        result += f"[{item}]" if isinstance(item, int) else f".{item}"
    return result
