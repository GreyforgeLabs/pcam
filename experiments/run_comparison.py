#!/usr/bin/env python3
"""Reproduce the bounded PCAM §45.7 comparison without making quality claims."""

from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import platform
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "reference/python"))

from pcam_runtime import (  # noqa: E402
    Contact,
    HostSnapshot,
    TickExecutor,
    TickInput,
    action_from_document,
    interaction_rules_from_document,
    load_document,
)
from pcam_runtime.state import SimulationState  # noqa: E402

TRACE_CONTRACT = (
    "tick",
    "input order",
    "buffer changes",
    "eligible transitions",
    "selected transitions",
    "rejected intents",
    "claim failures",
    "resource reservations",
    "progression quanta",
    "node changes",
    "predicate changes",
    "active semantic facts",
    "contact candidates",
    "candidate order",
    "interaction rules fired",
    "decision-record mutations",
    "provisional receipts",
    "effects emitted",
    "effect reduction",
    "state changes",
    "faults",
    "state digest",
)
VALIDATION_UNIVERSE = (
    "schema version",
    "identifier syntax",
    "positive bounded timing",
    "transition priority uniqueness",
    "reference integrity",
    "hit policy",
    "interaction stage order",
    "bounded expression shape",
    "phase projection coverage",
    "phase range bounds",
)


@dataclass
class Run:
    snapshot: dict[str, Any]
    observable: dict[str, Any]
    traces: list[dict[str, Any]]
    work_units: int


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _leaves(value: object) -> int:
    if isinstance(value, dict):
        return sum(_leaves(item) for item in value.values())
    if isinstance(value, list):
        return sum(_leaves(item) for item in value)
    return 1


def _contacts() -> tuple[dict[str, Any], ...]:
    return (
        {"id": "a-to-b", "source": 1, "target": 2},
        {"id": "a-to-b-dup", "source": 1, "target": 2},
        {"id": "b-to-a", "source": 2, "target": 1},
    )


def _simple_run(adapter: str, order: tuple[dict[str, Any], ...], scenario: dict[str, Any]) -> Run:
    actions: dict[str, dict[str, Any]] = {}
    for entity in (1, 2):
        if adapter == "fixed_fsm":
            actions[str(entity)] = {"node": "startup", "elapsed_ticks": 0}
        elif adapter == "statechart":
            actions[str(entity)] = {
                "node": "startup",
                "node_quanta": 0,
                "accumulator": 0,
            }
        else:
            actions[str(entity)] = {"frame": 0, "accumulator": 0}
    state: dict[str, Any] = {
        "tick": 0,
        "actions": actions,
        "hp": {"1": 100, "2": 100},
        "stagger": {"1": 0, "2": 0},
        "contact_ledger": [],
    }
    traces: list[dict[str, Any]] = []
    work_units = 0
    duration = scenario["node_durations"]
    for tick in range(scenario["ticks"]):
        node_changes: list[dict[str, object]] = []
        progression_quanta = 0
        for entity, action in state["actions"].items():
            before = _simple_node(adapter, action, tick)
            if adapter == "fixed_fsm":
                action["elapsed_ticks"] = tick + 1
                action["node"] = _fixed_node(tick)
                work_units += 1
            else:
                action["accumulator"] += scenario["units_per_tick"]
                quanta, action["accumulator"] = divmod(action["accumulator"], scenario["rate_scale"])
                progression_quanta += quanta
                work_units += 2
                for _ in range(quanta):
                    if adapter == "statechart":
                        _advance_statechart(action, duration)
                    else:
                        action["frame"] = min(24, action["frame"] + 1)
            after = _simple_node(adapter, action, tick)
            if after != before:
                node_changes.append({"entity": int(entity), "from": before, "to": after})
        effects: list[dict[str, Any]] = []
        candidate_order: list[str] = []
        if tick == scenario["contact_tick"]:
            for contact in sorted(order, key=lambda item: (item["source"], item["target"], item["id"])):
                candidate_order.append(contact["id"])
                work_units += 1
                source = str(contact["source"])
                target = str(contact["target"])
                if _simple_node(adapter, state["actions"][source], tick) != "active":
                    continue
                ledger_key = [int(source), int(target)]
                if ledger_key in state["contact_ledger"]:
                    continue
                state["contact_ledger"].append(ledger_key)
                state["hp"][target] -= scenario["damage"]
                target_active = _simple_node(adapter, state["actions"][target], tick) == "active"
                if not target_active:
                    state["stagger"][target] += scenario["stagger"]
                effects.append({"class": "DAMAGE", "source": int(source), "target": int(target)})
        state["tick"] = tick + 1
        traces.append(
            {
                "tick": tick,
                "progression quanta": progression_quanta,
                "node changes": node_changes,
                "candidate order": candidate_order,
                "effects emitted": effects,
                "state changes": {"hp": copy.deepcopy(state["hp"]), "stagger": copy.deepcopy(state["stagger"])},
            }
        )
    snapshot = copy.deepcopy(state)
    return Run(snapshot, _observable(state), traces, _semantic_work(traces, scenario["ticks"]))


def _fixed_node(tick: int) -> str:
    if tick < 24:
        return "startup"
    if tick < 34:
        return "active"
    if tick < 59:
        return "recovery"
    return "terminated"


def _simple_node(adapter: str, action: dict[str, Any], tick: int) -> str:
    if adapter == "fixed_fsm":
        return action["node"] if tick else "startup"
    if adapter == "statechart":
        return action["node"]
    frame = action["frame"]
    if frame < 10:
        return "startup"
    if frame < 14:
        return "active"
    if frame < 24:
        return "recovery"
    return "terminated"


def _advance_statechart(action: dict[str, Any], durations: dict[str, int]) -> None:
    node = action["node"]
    if node == "terminated":
        return
    action["node_quanta"] += 1
    if action["node_quanta"] < durations[node]:
        return
    action["node"] = {"startup": "active", "active": "recovery", "recovery": "terminated"}[node]
    action["node_quanta"] = 0


def _observable(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "hp": state["hp"],
        "stagger": state["stagger"],
        "terminated": all(
            (value.get("node") == "terminated" or value.get("frame") == 24)
            for value in state["actions"].values()
        ),
    }


def _pcam_setup() -> tuple[TickExecutor, Any, SimulationState, tuple[TickInput, ...]]:
    action_docs = [
        load_document(ROOT / "examples/heavy-strike.action.yaml"),
        load_document(ROOT / "examples/dodge.action.yaml"),
    ]
    definitions = tuple(action_from_document(document) for document in action_docs)
    interaction = load_document(ROOT / "examples/combat.interaction.yaml")
    rules = interaction_rules_from_document(interaction)
    executor = TickExecutor(
        definitions,
        interaction_rules=rules,
        effect_registry={
            "combat.damage": ("hp", -1),
            "combat.stagger": ("stagger", 1),
            "combat.parry_success": ("parry", 1),
        },
    )
    heavy = next(item for item in definitions if item.id == "greyforge.example.heavy_strike")
    state = executor.initial_state(
        resource_banks={
            "1": {"STAMINA": 100, "hp": 100, "stagger": 0},
            "2": {"STAMINA": 100, "hp": 100, "stagger": 0},
        },
        slot_capacities={"1": {"FULL_BODY": 1}, "2": {"FULL_BODY": 1}},
    )
    starts = (
        TickInput("start-a", 1, 0, "START", 0, action_definition_id=heavy.id),
        TickInput("start-b", 2, 0, "START", 0, action_definition_id=heavy.id),
    )
    return executor, heavy, state, starts


def _pcam_run(order: tuple[dict[str, Any], ...], include_projection: bool) -> Run:
    executor, _, state, starts = _pcam_setup()
    traces: list[dict[str, Any]] = []
    work_units = 0
    contacts = tuple(
        Contact(
            item["id"],
            item["source"],
            item["target"],
            "heavy_strike_hit",
            source_entity_id=item["source"],
            contact_id=item["id"],
        )
        for item in order
    )
    for tick in range(60):
        host = HostSnapshot(contacts=contacts) if tick == 24 else HostSnapshot()
        state, trace = executor.tick(state, starts if tick == 0 else (), host)
        record = dict(trace)
        if include_projection:
            record["phase projection"] = _phase_projection(state)
        traces.append(record)
        work_units += len(state.action_instances)
        work_units += len(trace.get("candidate_order", ()))
        work_units += len(trace.get("selected_transitions", ()))
    snapshot = state.to_snapshot()
    observable = {
        "hp": {entity: bank["hp"] for entity, bank in state.resource_banks.items()},
        "stagger": {entity: bank["stagger"] for entity, bank in state.resource_banks.items()},
        "terminated": all(item.lifecycle_state == "TERMINATED" for item in state.action_instances.values()),
    }
    return Run(snapshot, observable, traces, _semantic_work(traces, 60))


def _semantic_work(traces: list[dict[str, Any]], ticks: int) -> int:
    return (
        ticks * 2
        + sum(len(trace.get("candidate_order", trace.get("candidate order", ()))) for trace in traces)
        + sum(len(trace.get("node_changes", trace.get("node changes", ()))) for trace in traces)
    )


def _phase_projection(state: SimulationState) -> dict[str, int | None]:
    bases = {"startup": 0, "active": 10, "recovery": 14}
    return {
        instance_id: (
            bases[action.current_node_id] + action.node_step
            if action.lifecycle_state != "TERMINATED" and action.current_node_id in bases
            else None
        )
        for instance_id, action in state.action_instances.items()
    }


def _definition(subject: dict[str, Any]) -> object:
    if "definition" in subject:
        return subject["definition"]
    documents = [load_document(ROOT / path) for path in subject["definition_files"]]
    if subject["adapter"] == "pcam_core":
        core_documents = []
        for document in documents:
            if isinstance(document, dict) and document.get("kind") == "action":
                document = dict(document)
                document["profiles"] = {}
            core_documents.append(document)
        return core_documents
    return {"documents": documents, "projection_source": subject["projection_source"]}


def _run_subject(subject: dict[str, Any], order: tuple[dict[str, Any], ...], scenario: dict[str, Any]) -> Run:
    if subject["adapter"] in {"fixed_fsm", "statechart", "frame_data"}:
        return _simple_run(subject["adapter"], order, scenario)
    return _pcam_run(order, subject["adapter"] == "pcam24")


def build_report(*, include_timing: bool = False, timing_repetitions: int = 11) -> dict[str, Any]:
    manifest = json.loads((ROOT / "experiments/baselines/subjects.json").read_text())
    scenario = manifest["scenario"]
    orders = tuple(itertools.permutations(_contacts()))
    expected = {
        "hp": scenario["expected_hp"],
        "stagger": scenario["expected_stagger"],
        "terminated": True,
    }
    results: list[dict[str, Any]] = []
    for subject in manifest["subjects"]:
        runs = [_run_subject(subject, order, scenario) for order in orders]
        if any(run.observable != expected for run in runs):
            raise RuntimeError(f"{subject['id']} failed the shared observable contract")
        observable_digests = [_digest(run.observable) for run in runs]
        reference = runs[0]
        definition = _definition(subject)
        capabilities = set(subject["trace_capabilities"])
        results.append(
            {
                "subject_id": subject["id"],
                "runtime_state_bytes": len(_canonical(reference.snapshot)),
                "snapshot_bytes": len(_canonical(reference.snapshot)),
                "resimulation_cost": {
                    "logical_ticks": scenario["ticks"],
                    "deterministic_work_units": reference.work_units,
                    "unit_definition": "action-tick, canonical candidate, or node-transition commit",
                },
                "definition_complexity": {
                    "canonical_bytes": len(_canonical(definition)),
                    "leaf_values": _leaves(definition),
                },
                "validation_coverage": {
                    "declared_checks": len(subject["validation_checks"]),
                    "comparison_universe": len(VALIDATION_UNIVERSE),
                    "checks": subject["validation_checks"],
                },
                "replay_divergence": {
                    "contact_permutations": len(orders),
                    "divergent_runs": sum(item != observable_digests[0] for item in observable_digests),
                },
                "authoring_effort_proxy": {
                    "canonical_definition_bytes": len(_canonical(definition)),
                    "definition_leaf_values": _leaves(definition),
                    "not_human_time": True,
                },
                "debug_trace_clarity_proxy": {
                    "declared_contract_fields": len(capabilities.intersection(TRACE_CONTRACT)),
                    "contract_fields": len(TRACE_CONTRACT),
                    "fields": subject["trace_capabilities"],
                },
                "hidden_assumptions": {
                    "count": len(subject["hidden_assumptions"]),
                    "items": subject["hidden_assumptions"],
                },
                "ambiguous_interaction_cases": {
                    "count": len(subject["ambiguous_interaction_cases"]),
                    "items": subject["ambiguous_interaction_cases"],
                },
                "observable_digest": observable_digests[0],
                "trace_digest": _digest(reference.traces),
            }
        )
    report = {
        "experiment_version": manifest["experiment_version"],
        "scenario_id": scenario["id"],
        "environment": {
            "machine": platform.machine(),
            "platform": sys.platform,
            "python": platform.python_version(),
        },
        "measurement_policy": {
            "timing_status": "host timing is descriptive and committed separately from the deterministic report digest",
            "authoring_effort": "definition size and leaf counts are disclosed proxies, not labor measurements",
            "clarity": "declared trace-field coverage is a proxy, not a subjective quality score",
            "assumptions": "counts come from the reviewed subject manifest and are not inferred performance rankings",
        },
        "scenario_digest": _digest(scenario),
        "subjects_manifest_digest": _digest(manifest["subjects"]),
        "results": results,
    }
    report["report_digest"] = _digest(report)
    if include_timing:
        report["host_timing"] = _host_timing(manifest, timing_repetitions)
    return report


def _host_timing(manifest: dict[str, Any], repetitions: int) -> dict[str, Any]:
    if repetitions < 3:
        raise ValueError("timing repetitions must be at least three")
    order = _contacts()
    samples: dict[str, list[int]] = {}
    for subject in manifest["subjects"]:
        _run_subject(subject, order, manifest["scenario"])
        values = []
        for _ in range(repetitions):
            started = time.perf_counter_ns()
            _run_subject(subject, order, manifest["scenario"])
            values.append(time.perf_counter_ns() - started)
        samples[subject["id"]] = values
    return {
        "clock": "time.perf_counter_ns",
        "repetitions": repetitions,
        "scope": "one complete 60-tick replay from the declared initial state",
        "warning": "host timing is descriptive, environment-specific, and excluded from report_digest",
        "subjects": {
            identifier: {
                "median_ns": int(statistics.median(values)),
                "min_ns": min(values),
                "max_ns": max(values),
            }
            for identifier, values in samples.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", type=Path)
    parser.add_argument("--timing", action="store_true")
    parser.add_argument("--timing-repetitions", type=int, default=11)
    args = parser.parse_args()
    report = build_report(include_timing=args.timing, timing_repetitions=args.timing_repetitions)
    if args.check is not None:
        expected = json.loads(args.check.read_text())
        expected.pop("host_timing", None)
        report.pop("host_timing", None)
        if expected != report:
            print(json.dumps({"actual_digest": report["report_digest"], "matches": False}, sort_keys=True))
            return 1
        print(json.dumps({"matches": True, "report_digest": report["report_digest"]}, sort_keys=True))
        return 0
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
