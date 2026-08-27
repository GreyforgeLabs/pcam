"""PCAM-24 source validation and compilation into ordinary PCAM Core."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .schema import validate_document


def compile_pcam24(source: dict[str, Any]) -> dict[str, Any]:
    diagnostics = validate_document(source)
    if diagnostics:
        message = "; ".join(f"{item.path}: {item.message}" for item in diagnostics)
        raise ValueError(message)

    lifecycle = source["lifecycle"]
    nodes: dict[str, Any] = {
        "timeline": {
            "id": "timeline",
            "mode": "TIMED",
            "duration_quanta": 24,
            "seekable": True,
            "entry_assignments": [],
            "entry_effects": [],
            "exit_assignments": [],
            "exit_effects": [],
            "tags": [],
            "extensions": {},
        }
    }
    target: dict[str, Any]
    cycle_delta = 0
    assignments: list[dict[str, Any]] = []
    if lifecycle == "TERMINATE":
        target = {"kind": "TERMINATE"}
    elif lifecycle == "LOOP":
        target = {"kind": "NODE", "node": "timeline", "target_step": 0}
        cycle_delta = 1
    else:
        target = {"kind": "NODE", "node": "timeline", "target_step": 23}
        assignments = [{"target": "action.current_rate_units", "value": {"literal": 0}}]

    predicates = {
        tag: {
            "track_edges": True,
            "metadata": {"profile": "pcam24", "ranges": deepcopy(ranges)},
            "expression": _ranges_expression(ranges),
        }
        for tag, ranges in sorted(source["tags"].items(), key=lambda item: item[0].encode("utf-8"))
    }
    transition = {
        "id": f"timeline_{lifecycle.lower()}",
        "source_node": "timeline",
        "evaluation_point": "AFTER_QUANTUM",
        "guard": {
            "op": "gte",
            "args": [{"ref": "action.node_step"}, {"literal": 24}],
        },
        "priority": 100,
        "target": target,
        "input_match": None,
        "event_match": None,
        "claims": [],
        "consume_policy": "NEVER",
        "exit_assignments": [],
        "assignments": assignments,
        "entry_assignments": [],
        "effects": [],
        "cycle_delta": cycle_delta,
        "metadata": {"compiled_from": "pcam24"},
    }
    projection = [
        {"node": "timeline", "step_range": [0, 24], "phase_range": [0, 24]}
    ]

    return {
        "pcam_version": "3.0",
        "kind": "action",
        "id": source["id"],
        "revision": source["revision"],
        "metadata": deepcopy(source.get("metadata", {})),
        "limits": {
            "max_internal_transitions_per_tick": 8,
            "buffer_capacity": 8,
            "buffer_overflow_policy": "DROP_OLDEST",
        },
        "rate": deepcopy(source["rate"]),
        "parameters": {},
        "registers": {},
        "imports": {},
        "initial_node": "timeline",
        "nodes": nodes,
        "predicates": predicates,
        "semantic_facts": [],
        "transitions": [transition],
        "slot_claims": [],
        "profiles": {
            "pcam24": {
                "lifecycle": lifecycle,
                "projection": projection,
                "tags": deepcopy(source["tags"]),
            }
        },
        "extensions": deepcopy(source.get("extensions", {})),
    }


def _ranges_expression(ranges: list[list[int]]) -> dict[str, Any]:
    alternatives: list[dict[str, Any]] = []
    for start, end in ranges:
        alternatives.append(
            {
                "op": "and",
                "args": [
                    {"op": "eq", "args": [{"ref": "action.node"}, {"literal": "timeline"}]},
                    {"op": "gte", "args": [{"ref": "action.node_step"}, {"literal": start}]},
                    {"op": "lt", "args": [{"ref": "action.node_step"}, {"literal": end}]},
                ],
            }
        )
    if len(alternatives) == 1:
        return alternatives[0]
    return {"op": "or", "args": alternatives}
