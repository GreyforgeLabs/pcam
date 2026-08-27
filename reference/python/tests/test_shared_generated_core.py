import importlib.util
import json
from pathlib import Path

from pcam_runtime import (
    ActionDefinition,
    EffectEnvelope,
    InteractionCandidate,
    InteractionRule,
    NodeDefinition,
    RuleOperation,
    RuntimeProfile,
    SemanticFact,
    TickExecutor,
    TickInput,
    canonical_candidates,
    reduce_effects,
    resolve_candidate,
)

ROOT = Path(__file__).resolve().parents[3]
CORPUS_PATH = ROOT / "tests/generated/core-properties-v1.json"
GENERATOR_PATH = ROOT / "experiments/generate_core_properties.py"


def _corpus():
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


def _load_generator():
    spec = importlib.util.spec_from_file_location("pcam_generate_core_properties", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_rate_case(case):
    definition = ActionDefinition(
        id=f"GENERATED_RATE_{case['id'].removeprefix('rate-')}",
        rate_scale=case["scale"],
        units_per_tick=case["units_per_tick"],
        nodes=(NodeDefinition("RUN"),),
    )
    executor = TickExecutor(
        (definition,), RuntimeProfile(max_quanta_per_action_per_tick=128)
    )
    state = executor.initial_state()
    for tick_index in range(case["warmup_ticks"]):
        inputs = ()
        if tick_index == 0:
            inputs = (
                TickInput(
                    input_id=f"start-{case['id']}",
                    source_entity_id=1,
                    sequence=0,
                    command_id="START",
                    assigned_tick=0,
                    action_definition_id=definition.id,
                ),
            )
        state, _ = executor.tick(state, inputs)

    restored = executor.restore(executor.save(state))
    direct = state
    for _ in range(case["continuation_ticks"]):
        direct, left = executor.tick(direct)
        restored, right = executor.tick(restored)
        assert left["state_digest"] == right["state_digest"]
    assert direct.to_snapshot() == restored.to_snapshot()

    repeated = executor.initial_state()
    for tick_index in range(case["warmup_ticks"] + case["continuation_ticks"]):
        inputs = ()
        if tick_index == 0:
            inputs = (
                TickInput(
                    input_id=f"start-{case['id']}",
                    source_entity_id=1,
                    sequence=0,
                    command_id="START",
                    assigned_tick=0,
                    action_definition_id=definition.id,
                ),
            )
        repeated, _ = executor.tick(repeated, inputs)
    assert repeated.state_hash() == direct.state_hash()
    return direct.action_instances["1"]


def _reduced_record(effect):
    return {
        "target_entity_id": effect.target_entity_id,
        "effect_type": effect.effect_type,
        "reducer": effect.reducer,
        "value": effect.value,
        "source_effect_ids": list(effect.source_effect_ids),
    }


def _rule(value):
    return InteractionRule(
        rule_id=value["rule_id"],
        stage=value["stage"],
        order=value["order"],
        condition=value["condition"],
        operations=tuple(
            RuleOperation(operation["op"], operation.get("data"))
            for operation in value["operations"]
        ),
        stop_stage=value.get("stop_stage", False),
        stop_pipeline=value.get("stop_pipeline", False),
    )


def _rule_summary(case, values):
    decision = resolve_candidate(
        InteractionCandidate(**case["candidate"]),
        SemanticFact("generated-offense", "OFFENSE"),
        {},
        tuple(_rule(value) for value in values),
    )
    return {
        "status": decision.status,
        "decision_tags": list(decision.decision_tags),
        "trace_rule_ids": [entry["rule_id"] for entry in decision.trace],
    }


def test_generated_core_corpus_is_reproducible():
    assert _load_generator().render_corpus() == CORPUS_PATH.read_bytes()


def test_python_shared_generated_rates_repeat_and_restore_exactly():
    for case in _corpus()["rate_restore_cases"]:
        action = _run_rate_case(case)
        assert action.local_step == case["expected_local_step"], case["id"]
        assert action.quantum_accumulator == case["expected_quantum_accumulator"], case["id"]


def test_python_shared_generated_effect_aggregation_is_permutation_invariant():
    for case in _corpus()["effect_aggregation_cases"]:
        results = []
        for field in ("effects", "shuffled_effects"):
            reduced, rejected = reduce_effects(
                tuple(EffectEnvelope(**value) for value in case[field])
            )
            assert rejected == ()
            assert len(reduced) == 1
            results.append(_reduced_record(reduced[0]))
        assert results[0] == results[1] == case["expected"], case["id"]


def test_python_shared_generated_candidate_permutations_have_one_canonical_order():
    for case in _corpus()["candidate_permutation_cases"]:
        candidates = tuple(InteractionCandidate(**value) for value in case["candidates"])
        reversed_candidates = tuple(reversed(candidates))
        expected = case["expected_candidate_ids"]
        assert [item.candidate_id for item in canonical_candidates(candidates)] == expected
        assert [item.candidate_id for item in canonical_candidates(reversed_candidates)] == expected


def test_python_shared_generated_rule_sets_ignore_definition_enumeration():
    for case in _corpus()["interaction_rule_cases"]:
        expected = {
            "status": "ACCEPTED",
            "decision_tags": case["expected_decision_tags"],
            "trace_rule_ids": case["expected_trace_rule_ids"],
        }
        assert _rule_summary(case, case["rules"]) == expected, case["id"]
        assert _rule_summary(case, case["shuffled_rules"]) == expected, case["id"]
