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
    "conformance_manifest": "conformance-manifest.schema.json",
}

CONFORMANCE_REQUIREMENTS = {
    "PCAM-DEF-3": {
        "schema_validation",
        "reference_resolution",
        "graph_validation",
        "predicate_cycle_detection",
        "priority_validation",
        "limit_validation",
        "canonical_hashing",
        "meaningful_diagnostics",
    },
    "PCAM-RUN-3": {
        "normative_tick_pipeline",
        "action_progression",
        "transitions",
        "predicates",
        "buffers",
        "intents_and_claims",
        "parent_child_actions",
        "freeze_tokens",
        "interaction_resolution",
        "ledgers",
        "effect_reduction",
        "snapshot_and_restore",
        "canonical_state_digest",
    },
    "PCAM-DET-3": {
        "pcam_run_3",
        "deterministic_host_imports",
        "deterministic_contact_generation",
        "deterministic_host_effects",
        "deterministic_numeric_behavior",
        "cross_run_state_digest_identity",
    },
    "PCAM-RB-3": {
        "pcam_det_3",
        "input_history",
        "snapshot_history",
        "restore_and_resimulation",
        "prediction_declaration",
        "late_input_correction",
        "presentation_effect_deduplication",
        "rollback_equivalence_vectors",
    },
    "PCAM-24-3": {
        "valid_24_cell_schema",
        "half_open_range_semantics",
        "overlapping_tags",
        "lifecycle_compilation",
        "rational_rate_advancement",
        "phase_projection",
        "explicit_migration_warnings",
        "no_phase_only_state_claims",
    },
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
        diagnostics.extend(_floating_point_diagnostics(document))
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
    if kind == "conformance_manifest":
        return _conformance_diagnostics(document)
    return []


def _conformance_diagnostics(document: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    claims = document["claims"]
    for class_id, expected in CONFORMANCE_REQUIREMENTS.items():
        claim = claims[class_id]
        requirements = claim["requirements"]
        actual = set(requirements)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.claims.{class_id}.requirements",
                    f"requirement set mismatch; missing={missing}, extra={extra}",
                    PCAMFault.STATE_INVARIANT_FAILURE.value,
                )
            )
        for requirement_id, requirement in requirements.items():
            evidence = requirement["evidence"]
            if requirement["status"] == "PASS" and not evidence:
                diagnostics.append(
                    Diagnostic(
                        ResultCode.DEFINITION_REJECTED.value,
                        f"$.claims.{class_id}.requirements.{requirement_id}.evidence",
                        "PASS requires at least one evidence path",
                        PCAMFault.STATE_INVARIANT_FAILURE.value,
                    )
                )
            for index, raw_path in enumerate(evidence):
                path = Path(raw_path)
                safe = not path.is_absolute() and ".." not in path.parts
                exists = safe and (repository_root() / path).is_file()
                if not exists:
                    diagnostics.append(
                        Diagnostic(
                            ResultCode.DEFINITION_REJECTED.value,
                            f"$.claims.{class_id}.requirements.{requirement_id}.evidence[{index}]",
                            "evidence must be an existing repository-relative file",
                            PCAMFault.STATE_INVARIANT_FAILURE.value,
                        )
                    )
        if claim["claimed"] and any(item["status"] != "PASS" for item in requirements.values()):
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.claims.{class_id}.claimed",
                    "a claimed conformance class cannot contain OPEN requirements",
                    PCAMFault.STATE_INVARIANT_FAILURE.value,
                )
            )
    dependencies = {"PCAM-DET-3": "PCAM-RUN-3", "PCAM-RB-3": "PCAM-DET-3"}
    for class_id, dependency in dependencies.items():
        if claims[class_id]["claimed"] and not claims[dependency]["claimed"]:
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.claims.{class_id}.claimed",
                    f"{class_id} requires claimed {dependency}",
                    PCAMFault.STATE_INVARIANT_FAILURE.value,
                )
            )
    return diagnostics


def _action_diagnostics(document: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    nodes = document.get("nodes", {})
    predicates = document.get("predicates", {})
    transitions = document.get("transitions", [])
    initial_node = document.get("initial_node")
    register_ids = set(document.get("registers", {}))

    def check_assignments(assignments: object, path: str) -> None:
        if not isinstance(assignments, list):
            return
        prefix = "action.register."
        for assignment_index, assignment in enumerate(assignments):
            if not isinstance(assignment, dict):
                continue
            target = assignment.get("target")
            register_id = target.removeprefix(prefix) if isinstance(target, str) else ""
            if not isinstance(target, str) or not target.startswith(prefix) or register_id not in register_ids:
                diagnostics.append(
                    Diagnostic(
                        ResultCode.DEFINITION_REJECTED.value,
                        f"{path}[{assignment_index}].target",
                        f"assignment target must name a declared action register: {target!r}",
                        PCAMFault.MISSING_REFERENCE.value,
                    )
                )
    if initial_node not in nodes:
        diagnostics.append(
            Diagnostic(
                ResultCode.DEFINITION_REJECTED.value,
                "$.initial_node",
                f"unknown initial node: {initial_node!r}",
                PCAMFault.MISSING_REFERENCE.value,
            )
        )
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
        check_assignments(node.get("entry_assignments"), f"$.nodes.{node_name}.entry_assignments")
        check_assignments(node.get("exit_assignments"), f"$.nodes.{node_name}.exit_assignments")
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
    for collection_name, initial_key in (("parameters", "default"), ("registers", "initial")):
        for declaration_id, declaration in document.get(collection_name, {}).items():
            minimum = declaration.get("minimum")
            maximum = declaration.get("maximum")
            if isinstance(minimum, int) and isinstance(maximum, int) and minimum > maximum:
                diagnostics.append(
                    Diagnostic(
                        ResultCode.DEFINITION_REJECTED.value,
                        f"$.{collection_name}.{declaration_id}.minimum",
                        "minimum must not exceed maximum",
                        PCAMFault.STATE_INVARIANT_FAILURE.value,
                    )
                )
            initial = declaration.get(initial_key)
            if type(initial) is int and (
                (isinstance(minimum, int) and initial < minimum)
                or (isinstance(maximum, int) and initial > maximum)
            ):
                diagnostics.append(
                    Diagnostic(
                        ResultCode.DEFINITION_REJECTED.value,
                        f"$.{collection_name}.{declaration_id}.{initial_key}",
                        f"{initial_key} is outside declared bounds",
                        PCAMFault.STATE_INVARIANT_FAILURE.value,
                    )
                )
            if declaration.get("type") == "U64" and type(initial) is int and initial < 0:
                diagnostics.append(
                    Diagnostic(
                        ResultCode.DEFINITION_REJECTED.value,
                        f"$.{collection_name}.{declaration_id}.{initial_key}",
                        f"{initial_key} must be unsigned",
                        PCAMFault.STATE_INVARIANT_FAILURE.value,
                    )
                )
            allowed = declaration.get("allowed_values")
            if allowed is not None and initial_key in declaration and initial not in allowed:
                diagnostics.append(
                    Diagnostic(
                        ResultCode.DEFINITION_REJECTED.value,
                        f"$.{collection_name}.{declaration_id}.{initial_key}",
                        f"{initial_key} is not in allowed_values",
                        PCAMFault.STATE_INVARIANT_FAILURE.value,
                    )
                )
    seen_priorities: set[tuple[str, str, int]] = set()
    seen_transition_ids: set[str] = set()
    completion_sources: set[str] = set()
    for index, transition in enumerate(transitions):
        if not isinstance(transition, dict):
            continue
        source = transition.get("source_node")
        point = transition.get("evaluation_point")
        priority = transition.get("priority")
        transition_id = str(transition.get("id"))
        if transition_id in seen_transition_ids:
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.transitions[{index}].id",
                    "transition identifier must be unique",
                    PCAMFault.DUPLICATE_IDENTIFIER.value,
                )
            )
        seen_transition_ids.add(transition_id)
        if source not in nodes:
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.transitions[{index}].source_node",
                    f"unknown source node: {source!r}",
                    PCAMFault.MISSING_REFERENCE.value,
                )
            )
        if point == "AFTER_QUANTUM" and transition.get("claims"):
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.transitions[{index}].claims",
                    "AFTER_QUANTUM transitions cannot contain contested claims",
                    PCAMFault.STATE_INVARIANT_FAILURE.value,
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
        if isinstance(target, dict) and target.get("kind") == "NODE" and target.get("node") in nodes:
            target_node = nodes[target["node"]]
            target_step = int(target.get("target_step", 0))
            if target_step > 0 and not target_node.get("seekable"):
                diagnostics.append(
                    Diagnostic(
                        ResultCode.DEFINITION_REJECTED.value,
                        f"$.transitions[{index}].target.target_step",
                        "nonzero target step requires a seekable target node",
                        PCAMFault.STATE_INVARIANT_FAILURE.value,
                    )
                )
            duration = target_node.get("duration_quanta")
            if target_node.get("mode") == "TIMED" and isinstance(duration, int) and target_step >= duration:
                diagnostics.append(
                    Diagnostic(
                        ResultCode.DEFINITION_REJECTED.value,
                        f"$.transitions[{index}].target.target_step",
                        "target step must be less than the timed-node duration",
                        PCAMFault.STATE_INVARIANT_FAILURE.value,
                    )
                )
        for field in ("exit_assignments", "assignments", "entry_assignments"):
            check_assignments(transition.get(field), f"$.transitions[{index}].{field}")
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
    seen_fact_ids: set[str] = set()
    for index, fact in enumerate(document.get("semantic_facts", [])):
        fact_id = str(fact.get("id"))
        if fact_id in seen_fact_ids:
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.semantic_facts[{index}].id",
                    "semantic-fact identifier must be unique",
                    PCAMFault.DUPLICATE_IDENTIFIER.value,
                )
            )
        seen_fact_ids.add(fact_id)
        for reference in _expression_references(fact.get("when")):
            prefix = "action.predicate."
            if reference.startswith(prefix) and reference[len(prefix) :] not in predicates:
                diagnostics.append(
                    Diagnostic(
                        ResultCode.DEFINITION_REJECTED.value,
                        f"$.semantic_facts[{index}].when",
                        f"unknown predicate reference: {reference}",
                        PCAMFault.MISSING_REFERENCE.value,
                    )
                )
        policy = fact.get("hit_policy", {})
        if policy.get("kind") == "COOLDOWN_TICKS" and "cooldown_ticks" not in policy:
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.semantic_facts[{index}].hit_policy.cooldown_ticks",
                    "COOLDOWN_TICKS requires cooldown_ticks",
                    PCAMFault.MISSING_REFERENCE.value,
                )
            )
        if policy.get("kind") == "ONCE_PER_PREDICATE_ACTIVATION" and policy.get("predicate_id") not in predicates:
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.semantic_facts[{index}].hit_policy.predicate_id",
                    "predicate-activation policy requires a known predicate_id",
                    PCAMFault.MISSING_REFERENCE.value,
                )
            )
        if policy.get("kind") == "CUSTOM_LEDGER_KEY" and "custom_key_id" not in policy:
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.semantic_facts[{index}].hit_policy.custom_key_id",
                    "CUSTOM_LEDGER_KEY requires custom_key_id",
                    PCAMFault.MISSING_REFERENCE.value,
                )
            )
    profile = document.get("profiles", {}).get("pcam24")
    if isinstance(profile, dict):
        diagnostics.extend(_embedded_pcam24_diagnostics(profile, nodes))
    return diagnostics


def _interaction_diagnostics(document: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    seen: set[tuple[str, int]] = set()
    seen_ids: set[str] = set()
    for index, rule in enumerate(document.get("rules", [])):
        rule_id = str(rule.get("id"))
        if rule_id in seen_ids:
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.rules[{index}].id",
                    "interaction-rule identifier must be unique",
                    PCAMFault.DUPLICATE_IDENTIFIER.value,
                )
            )
        seen_ids.add(rule_id)
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
        for operation_index, operation in enumerate(rule.get("operations", [])):
            if operation.get("op") != "MATERIALIZE" or "REJECTED" not in operation.get("statuses", []):
                continue
            if not operation.get("effect_classes"):
                diagnostics.append(
                    Diagnostic(
                        ResultCode.DEFINITION_REJECTED.value,
                        f"$.rules[{index}].operations[{operation_index}].effect_classes",
                        "rejected materialization requires explicit effect_classes",
                        PCAMFault.STATE_INVARIANT_FAILURE.value,
                    )
                )
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


def _embedded_pcam24_diagnostics(profile: dict[str, Any], nodes: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    phase_ranges: list[tuple[int, int]] = []
    for index, projection in enumerate(profile.get("projection", [])):
        node_id = projection.get("node")
        if node_id not in nodes:
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.profiles.pcam24.projection[{index}].node",
                    f"unknown projection node: {node_id!r}",
                    PCAMFault.MISSING_REFERENCE.value,
                )
            )
        step_start, step_end = projection.get("step_range", (0, 0))
        phase_start, phase_end = projection.get("phase_range", (0, 0))
        if step_start >= step_end or phase_start >= phase_end:
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    f"$.profiles.pcam24.projection[{index}]",
                    "projection ranges must be nonempty half-open intervals",
                    PCAMFault.INVALID_PROFILE_RANGE.value,
                )
            )
        phase_ranges.append((phase_start, phase_end))
    ordered = sorted(phase_ranges)
    if ordered and (ordered[0][0] != 0 or ordered[-1][1] != 24 or any(a[1] != b[0] for a, b in zip(ordered, ordered[1:]))):
        diagnostics.append(
            Diagnostic(
                ResultCode.DEFINITION_REJECTED.value,
                "$.profiles.pcam24.projection",
                "phase projection must cover [0,24) exactly without gaps or overlaps",
                PCAMFault.INVALID_PROFILE_RANGE.value,
            )
        )
    for tag, ranges in profile.get("tags", {}).items():
        for index, (start, end) in enumerate(ranges):
            if start >= end:
                diagnostics.append(
                    Diagnostic(
                        ResultCode.DEFINITION_REJECTED.value,
                        f"$.profiles.pcam24.tags.{tag}[{index}]",
                        "PCAM-24 tag ranges must be nonempty half-open intervals",
                        PCAMFault.INVALID_PROFILE_RANGE.value,
                    )
                )
    return diagnostics


def _floating_point_diagnostics(document: object) -> list[Diagnostic]:
    diagnostics = []
    for path, value in _walk_values(document):
        if isinstance(value, float):
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    path,
                    "IEEE floating-point values are forbidden in authoritative documents",
                    PCAMFault.CANONICALIZATION_FAILURE.value,
                )
            )
        if type(value) is int and not (-(1 << 63) <= value <= (1 << 64) - 1):
            diagnostics.append(
                Diagnostic(
                    ResultCode.DEFINITION_REJECTED.value,
                    path,
                    "integer is outside the Core I64/U64 representable range",
                    PCAMFault.INTEGER_OVERFLOW.value,
                )
            )
    return diagnostics


def _walk_values(value: object, path: str = "$"):
    yield path, value
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_values(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_values(item, f"{path}[{index}]")


def _expression_references(expression: Any) -> set[str]:
    return {
        str(value)
        for path, value in _walk_values(expression)
        if path.endswith(".ref") and isinstance(value, str)
    }


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
