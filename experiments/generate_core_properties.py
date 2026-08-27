#!/usr/bin/env python3
"""Generate the bounded shared PCAM Core property corpus."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "tests/generated/core-properties-v1.json"
SEED = 0x5043414D39


def _rate_cases(generator: random.Random) -> list[dict[str, object]]:
    cases = []
    for index in range(24):
        scale = generator.randint(1, 32)
        units = generator.randint(0, 64)
        warmup_ticks = generator.randint(1, 8)
        continuation_ticks = generator.randint(1, 8)
        total_units = (warmup_ticks + continuation_ticks) * units
        cases.append(
            {
                "id": f"rate-{index:03d}",
                "scale": scale,
                "units_per_tick": units,
                "warmup_ticks": warmup_ticks,
                "continuation_ticks": continuation_ticks,
                "expected_local_step": total_units // scale,
                "expected_quantum_accumulator": total_units % scale,
            }
        )
    return cases


def _action_graph_cases(generator: random.Random) -> list[dict[str, object]]:
    cases = []
    for index in range(24):
        node_count = generator.randint(2, 8)
        ticks = node_count + generator.randint(1, 4)
        cases.append(
            {
                "id": f"graph-{index:03d}",
                "node_count": node_count,
                "ticks": ticks,
                "expected_node": f"N{node_count - 1}",
                "expected_local_step": ticks,
                "expected_node_step": ticks - (node_count - 1),
                "expected_transition_serial": node_count - 1,
            }
        )
    return cases


def _transition_guard_cases(generator: random.Random) -> list[dict[str, object]]:
    return [
        {
            "id": f"guard-{index:03d}",
            "threshold": generator.randint(0, 20),
            "ticks": 24,
            "expected_node": "DONE",
            "expected_transition_serial": 1,
        }
        for index in range(24)
    ]


def _input_order_cases(generator: random.Random) -> list[dict[str, object]]:
    cases = []
    for case_index in range(24):
        input_count = generator.randint(3, 7)
        sequences = generator.sample(range(1, 1000), input_count)
        inputs = [
            {
                "assigned_tick": 1,
                "source_entity_id": 1,
                "sequence": sequence,
                "command_id": generator.choice(["CMD_A", "CMD_B", "CMD_C"]),
                "payload": {"value": generator.randint(0, 100)},
                "input_id": f"input-{case_index:03d}-{index:02d}",
            }
            for index, sequence in enumerate(sequences)
        ]
        generator.shuffle(inputs)
        shuffled = [dict(value) for value in inputs]
        generator.shuffle(shuffled)
        expected = sorted(
            inputs,
            key=lambda value: (
                int(value["source_entity_id"]),
                int(value["sequence"]),
                str(value["command_id"]).encode(),
                str(value["input_id"]).encode(),
            ),
        )
        cases.append(
            {
                "id": f"input-order-{case_index:03d}",
                "inputs": inputs,
                "shuffled_inputs": shuffled,
                "expected_input_ids": [value["input_id"] for value in expected],
            }
        )
    return cases


def _freeze_token_cases(generator: random.Random) -> list[dict[str, object]]:
    domains = ("BUFFER_EXPIRY", "INPUT_CAPTURE", "PROGRESSION")
    cases = []
    for case_index in range(24):
        tokens = []
        for token_index in range(generator.randint(1, 8)):
            token_domains = sorted(
                generator.sample(domains, generator.randint(1, len(domains)))
            )
            tokens.append(
                {
                    "token_id": token_index + 1,
                    "source_id": generator.randint(1, 4),
                    "target_id": generator.choice((1, 2)),
                    "activation_tick": generator.randint(1, 3),
                    "remaining_ticks": generator.randint(1, 4),
                    "domains": token_domains,
                    "accrual_policy": generator.choice(("HOLD", "ACCRUE")),
                    "stack_group": f"generated-{case_index:03d}-{token_index:02d}",
                    "stack_policy": "INDEPENDENT",
                    "metadata": {"case": case_index, "token": token_index},
                }
            )
        shuffled_tokens = json.loads(json.dumps(tokens))
        generator.shuffle(shuffled_tokens)
        working = json.loads(json.dumps(tokens))
        expected_ticks = []
        for tick in range(8):
            targets = {}
            for target_id in (1, 2):
                active = [
                    token
                    for token in working
                    if token["target_id"] == target_id
                    and token["activation_tick"] <= tick
                    and token["remaining_ticks"] > 0
                ]
                progression = [
                    token
                    for token in active
                    if "PROGRESSION" in token["domains"]
                ]
                targets[str(target_id)] = {
                    "domains": {
                        domain: any(domain in token["domains"] for token in active)
                        for domain in domains
                    },
                    "progression_accrual": (
                        "HOLD"
                        if any(
                            token["accrual_policy"] == "HOLD"
                            for token in progression
                        )
                        else "ACCRUE" if progression else None
                    ),
                }
            next_working = []
            for token in working:
                updated = dict(token)
                if updated["activation_tick"] <= tick:
                    updated["remaining_ticks"] -= 1
                if updated["remaining_ticks"] > 0:
                    next_working.append(updated)
            working = next_working
            expected_ticks.append(
                {
                    "tick": tick,
                    "targets": targets,
                    "remaining_after_tick": [
                        {
                            "token_id": token["token_id"],
                            "remaining_ticks": token["remaining_ticks"],
                        }
                        for token in sorted(
                            working, key=lambda token: int(token["token_id"])
                        )
                    ],
                }
            )
        cases.append(
            {
                "id": f"freeze-token-{case_index:03d}",
                "tokens": tokens,
                "shuffled_tokens": shuffled_tokens,
                "expected_ticks": expected_ticks,
            }
        )
    return cases


def _rollback_correction_cases(generator: random.Random) -> list[dict[str, object]]:
    cases = []
    for case_index in range(24):
        scale = generator.randint(1, 8)
        units = generator.randint(0, 8)
        total_ticks = generator.randint(3, 8)
        corrected_tick = generator.randint(0, total_ticks - 1)
        corrected_has_start = bool(generator.getrandbits(1))
        advancing_ticks = total_ticks - corrected_tick if corrected_has_start else 0
        total_units = advancing_ticks * units
        cases.append(
            {
                "id": f"rollback-correction-{case_index:03d}",
                "scale": scale,
                "units_per_tick": units,
                "total_ticks": total_ticks,
                "corrected_tick": corrected_tick,
                "predicted_has_start": not corrected_has_start,
                "corrected_has_start": corrected_has_start,
                "expected_action_count": 1 if corrected_has_start else 0,
                "expected_local_step": total_units // scale,
                "expected_quantum_accumulator": total_units % scale,
                "expected_rewind_ticks": total_ticks - corrected_tick,
            }
        )
    return cases


def _parent_child_cases(generator: random.Random) -> list[dict[str, object]]:
    cases = []
    for case_index in range(16):
        capacity = generator.randint(1, 4)
        child_count = generator.randint(1, capacity)
        cases.append(
            {
                "id": f"parent-child-{case_index:03d}",
                "child_slot_id": generator.choice(("AUX", "SUB", "WEAPON")),
                "capacity": capacity,
                "child_count": child_count,
                "expected_action_count": child_count + 1,
                "expected_child_instance_ids": list(range(2, child_count + 2)),
                "expected_next_action_instance_id": child_count + 2,
            }
        )
    return cases


def _numeric_division_cases(generator: random.Random) -> list[dict[str, object]]:
    cases = []
    for case_index in range(32):
        dividend = generator.randint(-1_000_000_000, 1_000_000_000)
        divisor = generator.randint(1, 1_000_000)
        quotient, remainder = divmod(dividend, divisor)
        cases.append(
            {
                "id": f"numeric-division-{case_index:03d}",
                "dividend": dividend,
                "divisor": divisor,
                "quotient": quotient,
                "remainder": remainder,
            }
        )
    return cases


def _numeric_ratio_cases(generator: random.Random) -> list[dict[str, object]]:
    cases = []
    for case_index in range(32):
        value = generator.randint(-1_000_000, 1_000_000)
        numerator = generator.randint(-1_000, 1_000)
        denominator = generator.randint(1, 1_000)
        cases.append(
            {
                "id": f"numeric-ratio-{case_index:03d}",
                "value": value,
                "numerator": numerator,
                "denominator": denominator,
                "result": (value * numerator) // denominator,
            }
        )
    return cases


def _bounded_integer(
    value: int, bits: int, signed: bool, policy: str
) -> tuple[int | None, str | None]:
    minimum = -(1 << (bits - 1)) if signed else 0
    maximum = (1 << (bits - (1 if signed else 0))) - 1
    if minimum <= value <= maximum:
        return value, None
    if policy == "FAULT":
        return None, "INTEGER_OVERFLOW"
    if policy == "SATURATE":
        return min(max(value, minimum), maximum), None
    modulus = 1 << bits
    wrapped = value % modulus
    if signed and wrapped > maximum:
        wrapped -= modulus
    return wrapped, None


def _numeric_overflow_cases(generator: random.Random) -> list[dict[str, object]]:
    cases = []
    for case_index in range(24):
        domain = generator.choice(("I64", "U64"))
        policy = generator.choice(("FAULT", "SATURATE", "WRAP"))
        if domain == "I64":
            boundary = generator.choice((-(1 << 63), (1 << 63) - 1))
            direction = -1 if boundary < 0 else 1
        else:
            boundary = generator.choice((0, (1 << 64) - 1))
            direction = -1 if boundary == 0 else 1
        value = boundary + direction * generator.randint(1, 4096)
        result, fault = _bounded_integer(value, 64, domain == "I64", policy)
        cases.append(
            {
                "id": f"numeric-overflow-{case_index:03d}",
                "domain": domain,
                "input": str(value),
                "policy": policy,
                "result": result,
                "fault": fault,
            }
        )
    return cases


def _effect_key(effect: dict[str, object]) -> tuple[object, ...]:
    return (
        effect["target_entity_id"],
        str(effect["effect_type"]).encode(),
        -int(effect["priority"]),
        effect["source_entity_id"],
        effect["source_action_instance_id"],
        str(effect["effect_id"]).encode(),
    )


def _effect_cases(generator: random.Random) -> list[dict[str, object]]:
    cases = []
    for case_index in range(32):
        effects = []
        for effect_index in range(generator.randint(2, 12)):
            effects.append(
                {
                    "effect_id": f"generated-{case_index:03d}-{effect_index:02d}",
                    "effect_type": "generated.sum",
                    "effect_class": "RESOURCE",
                    "source_entity_id": generator.randint(1, 4),
                    "target_entity_id": 1,
                    "source_action_instance_id": generator.randint(1, 16),
                    "origin_tick": case_index,
                    "priority": generator.randint(-4, 12),
                    "payload": generator.randint(-100, 100),
                    "reducer": "SUM",
                    "authoritative": True,
                }
            )
        shuffled = [dict(effect) for effect in effects]
        generator.shuffle(shuffled)
        ordered = sorted(effects, key=_effect_key)
        cases.append(
            {
                "id": f"effect-{case_index:03d}",
                "effects": effects,
                "shuffled_effects": shuffled,
                "expected": {
                    "target_entity_id": 1,
                    "effect_type": "generated.sum",
                    "reducer": "SUM",
                    "value": sum(int(effect["payload"]) for effect in effects),
                    "source_effect_ids": [effect["effect_id"] for effect in ordered],
                },
            }
        )
    return cases


def _candidate_key(candidate: dict[str, object]) -> tuple[object, ...]:
    return (
        candidate["source_entity_id"],
        candidate["target_entity_id"],
        candidate["source_action_instance_id"],
        str(candidate["offense_fact_id"]).encode(),
        str(candidate.get("defense_fact_id") or "").encode(),
        str(candidate["contact_partition"]).encode(),
        str(candidate["contact_id"]).encode(),
        str(candidate["candidate_id"]).encode(),
    )


def _candidate_cases(generator: random.Random) -> list[dict[str, object]]:
    cases = []
    for case_index in range(32):
        candidates = []
        for candidate_index in range(generator.randint(3, 8)):
            candidates.append(
                {
                    "tick": case_index,
                    "candidate_id": f"candidate-{case_index:03d}-{candidate_index:02d}",
                    "source_entity_id": generator.randint(1, 4),
                    "target_entity_id": generator.randint(1, 4),
                    "source_action_instance_id": generator.randint(1, 12),
                    "offense_fact_id": generator.choice(["alpha", "beta", "gamma"]),
                    "defense_fact_id": generator.choice([None, "armor", "guard"]),
                    "contact_partition": generator.choice(["body", "default", "weapon"]),
                    "contact_id": f"contact-{generator.randint(0, 6):02d}",
                    "host_context": {},
                }
            )
        generator.shuffle(candidates)
        cases.append(
            {
                "id": f"candidate-{case_index:03d}",
                "candidates": candidates,
                "expected_candidate_ids": [
                    candidate["candidate_id"] for candidate in sorted(candidates, key=_candidate_key)
                ],
            }
        )
    return cases


def _rule_cases(generator: random.Random) -> list[dict[str, object]]:
    cases = []
    for case_index in range(24):
        orders = generator.sample(range(1, 1000), generator.randint(2, 8))
        rules = [
            {
                "rule_id": f"rule-{case_index:03d}-{order:04d}",
                "stage": "MODIFICATION",
                "order": order,
                "condition": {"literal": True},
                "operations": [
                    {"op": "ADD_DECISION_TAG", "data": {"tag": f"T{order:04d}"}}
                ],
                "stop_stage": False,
                "stop_pipeline": False,
            }
            for order in orders
        ]
        shuffled = [json.loads(json.dumps(rule)) for rule in rules]
        generator.shuffle(shuffled)
        ordered = sorted(rules, key=lambda rule: int(rule["order"]))
        cases.append(
            {
                "id": f"rules-{case_index:03d}",
                "candidate": {
                    "tick": case_index,
                    "candidate_id": f"rule-candidate-{case_index:03d}",
                    "source_entity_id": 1,
                    "target_entity_id": 2,
                    "source_action_instance_id": 1,
                    "offense_fact_id": "generated-offense",
                    "contact_id": "generated-contact",
                    "contact_partition": "default",
                    "host_context": {},
                    "defense_fact_id": None,
                },
                "rules": rules,
                "shuffled_rules": shuffled,
                "expected_decision_tags": sorted(
                    (rule["operations"][0]["data"]["tag"] for rule in rules)
                ),
                "expected_trace_rule_ids": [rule["rule_id"] for rule in ordered],
            }
        )
    return cases


def build_corpus() -> dict[str, object]:
    generator = random.Random(SEED)
    rate_restore_cases = _rate_cases(generator)
    effect_aggregation_cases = _effect_cases(generator)
    candidate_permutation_cases = _candidate_cases(generator)
    interaction_rule_cases = _rule_cases(generator)
    action_graph_cases = _action_graph_cases(generator)
    transition_guard_cases = _transition_guard_cases(generator)
    input_order_cases = _input_order_cases(generator)
    freeze_token_cases = _freeze_token_cases(generator)
    rollback_correction_cases = _rollback_correction_cases(generator)
    parent_child_cases = _parent_child_cases(generator)
    numeric_division_cases = _numeric_division_cases(generator)
    numeric_ratio_cases = _numeric_ratio_cases(generator)
    numeric_overflow_cases = _numeric_overflow_cases(generator)
    return {
        "pcam_generated_corpus_version": "1",
        "kind": "generated_core_properties",
        "id": "pcam.generated.core.v1",
        "seed": SEED,
        "generator": "experiments/generate_core_properties.py",
        "rate_restore_cases": rate_restore_cases,
        "action_graph_cases": action_graph_cases,
        "transition_guard_cases": transition_guard_cases,
        "input_order_cases": input_order_cases,
        "freeze_token_cases": freeze_token_cases,
        "rollback_correction_cases": rollback_correction_cases,
        "parent_child_cases": parent_child_cases,
        "numeric_division_cases": numeric_division_cases,
        "numeric_ratio_cases": numeric_ratio_cases,
        "numeric_overflow_cases": numeric_overflow_cases,
        "effect_aggregation_cases": effect_aggregation_cases,
        "candidate_permutation_cases": candidate_permutation_cases,
        "interaction_rule_cases": interaction_rule_cases,
    }


def render_corpus() -> bytes:
    return (json.dumps(build_corpus(), indent=2, sort_keys=True) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rendered = render_corpus()
    if args.check:
        matches = args.output.exists() and args.output.read_bytes() == rendered
        print(json.dumps({"matches": matches, "output": str(args.output)}))
        return 0 if matches else 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(rendered)
    print(json.dumps({"written": str(args.output), "bytes": len(rendered)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
